"""Bounded job diagnostics adapted from DevFeed, backed by Wardn's PostgreSQL.

A bounded process queue keeps logging off the execution path. An independent
transaction preserves flushed logs when an operation rolls back. Unflushed
records can be lost on process failure; these logs are not an audit trail.
"""

import atexit
import inspect
import json
import logging
import queue
import threading
import time
from contextlib import suppress
from functools import wraps
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.log_text import error_text, event_text
from app.core.logging import JsonFormatter, log_context

JobKind = Literal["mcp_operation", "scheduled_task", "agent_run"]
JOB_KINDS = {"mcp_operation", "scheduled_task", "agent_run"}
MAX_EVENT_BYTES = 16_384
logger = logging.getLogger(__name__)


def logged_job(kind: JobKind, *, phase: str = "execute"):
    """Propagate identifiers into nested awaits, heartbeat tasks and thread work."""

    def decorate(function):
        parameter = next(iter(inspect.signature(function).parameters))

        @wraps(function)
        async def wrapped(*args, **kwargs):
            job = args[0] if args else kwargs[parameter]
            identifier = getattr(job, "agent_run_id", job.id) if kind == "agent_run" else job.id
            with log_context(
                job_kind=kind,
                job_id=str(identifier),
                phase=phase,
                organization_id=str(job.organization_id),
                workspace_id=str(job.workspace_id) if job.workspace_id else None,
                worker_id=kwargs.get("worker_id"),
                attempt=getattr(job, "attempt_count", None),
            ):
                return await function(*args, **kwargs)

        return wrapped

    return decorate


def logged_agent_stream(function):
    """Scope each generator advance, never leave context bound across a yield."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        run = kwargs.get("agent_run")
        stream = function(*args, **kwargs)
        fields = (
            {}
            if run is None
            else {
                "job_kind": "agent_run",
                "job_id": str(run.id),
                "agent_run_id": str(run.id),
                "organization_id": str(run.organization_id),
                "workspace_id": str(run.workspace_id),
                "agent_id": str(run.agent_id),
            }
        )
        with log_context(**fields):
            logger.info("agent_execution_started")
        try:
            while True:
                with log_context(**fields):
                    try:
                        item = await anext(stream)
                    except StopAsyncIteration:
                        logger.info("agent_execution_finished")
                        break
                    except Exception:
                        logger.exception("agent_execution_failed")
                        raise
                yield item
        finally:
            with log_context(**fields):
                await stream.aclose()

    return wrapped


def encode_record(record: logging.LogRecord) -> dict | None:
    payload = JsonFormatter("worker").payload(record)
    if payload.get("job_kind") not in JOB_KINDS:
        return None
    try:
        organization_id = str(UUID(str(payload["organization_id"])))
        job_id = str(UUID(str(payload["job_id"])))
    except (KeyError, ValueError, TypeError):
        return None
    message = event_text(payload)
    error = error_text(payload, verbose=True)
    entry = {
        "timestamp": payload.pop("timestamp"),
        "level": payload.pop("level"),
        "message": message + (f" - {error}" if error else ""),
        "fields": payload,
    }
    if len(json.dumps(entry, ensure_ascii=True, allow_nan=False)) > MAX_EVENT_BYTES:
        entry["message"] = entry["message"][:1000]
        entry["fields"] = {
            key: payload[key]
            for key in ("event", "job_kind", "job_id", "organization_id", "workspace_id", "attempt")
            if key in payload
        }
        entry["fields"]["details_truncated"] = True
    return {
        "organization_id": organization_id,
        "job_kind": payload["job_kind"],
        "job_id": job_id,
        "entry": entry,
    }


def write_records(records: list[dict]) -> None:
    settings = get_settings()
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql")
    grouped: dict[tuple, list[dict]] = {}
    for record in records:
        key = (record["organization_id"], record["job_kind"], record["job_id"])
        grouped.setdefault(key, []).append(record["entry"])
    with psycopg.connect(
        url.render_as_string(hide_password=False),
        connect_timeout=1,
        options="-c statement_timeout=1000 -c lock_timeout=1000",
    ) as connection:
        for (organization_id, kind, job_id), entries in sorted(grouped.items()):
            # Serialize a job's writers before assigning IDs so cursors cannot skip
            # records committed out of order by overlapping worker attempts.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"runtime-logs:{organization_id}:{kind}:{job_id}",),
            )
            for entry in entries:
                connection.execute(
                    "INSERT INTO runtime_job_logs "
                    "(organization_id, job_kind, job_id, occurred_at, expires_at, entry) "
                    "VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s), %s)",
                    (
                        organization_id,
                        kind,
                        job_id,
                        entry["timestamp"],
                        settings.job_log_ttl_seconds,
                        Jsonb(entry),
                    ),
                )
            connection.execute(
                "DELETE FROM runtime_job_logs WHERE organization_id=%s AND job_kind=%s "
                "AND job_id=%s AND id < (SELECT id FROM runtime_job_logs "
                "WHERE organization_id=%s AND job_kind=%s AND job_id=%s "
                "ORDER BY id DESC OFFSET %s LIMIT 1)",
                (
                    organization_id,
                    kind,
                    job_id,
                    organization_id,
                    kind,
                    job_id,
                    settings.job_log_max_entries - 1,
                ),
            )
        connection.execute(
            "DELETE FROM runtime_job_logs WHERE id IN (SELECT id FROM runtime_job_logs "
            "WHERE expires_at < now() ORDER BY expires_at LIMIT 1000)"
        )


class JobLogHandler(logging.Handler):
    def __init__(self, writer=write_records):
        super().__init__(logging.DEBUG)
        self.pending: queue.Queue = queue.Queue(maxsize=2000)
        self.writer = writer
        self.stopping = threading.Event()
        self.retry_at = 0.0
        self.thread = threading.Thread(target=self.run, name="wardn-job-logs", daemon=True)
        self.thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        if self.stopping.is_set() or time.monotonic() < self.retry_at:
            return
        try:
            encoded = encode_record(record)
            if encoded is not None:
                self.pending.put_nowait(encoded)
        except Exception:
            # Logging must never fail an operation or expose a raw record.
            return

    def run(self) -> None:
        maintenance_at = time.monotonic() + 60
        while not self.stopping.is_set() or not self.pending.empty():
            try:
                first = self.pending.get(timeout=0.25)
            except queue.Empty:
                if time.monotonic() < maintenance_at or self.stopping.is_set():
                    continue
                first = None
                maintenance_at = time.monotonic() + 60
            batch = [first] if first is not None else []
            while len(batch) < 100:
                try:
                    batch.append(self.pending.get_nowait())
                except queue.Empty:
                    break
            try:
                if time.monotonic() >= self.retry_at:
                    self.writer(batch)
            except Exception:
                self.retry_at = time.monotonic() + 30
                with suppress(Exception):
                    logger.warning("job_log_storage_unavailable")
            finally:
                for _ in batch:
                    self.pending.task_done()

    def close(self) -> None:
        self.stopping.set()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)
        super().close()


def configure_job_log_capture() -> None:
    root = logging.getLogger()
    handlers = [handler for handler in root.handlers if isinstance(handler, JobLogHandler)]
    if not get_settings().job_logs_enabled:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
        return
    if not handlers:
        handler = JobLogHandler()
        root.addHandler(handler)
        atexit.register(handler.close)
    # DEBUG diagnostics are captured independently of the console handler threshold.
    logging.getLogger("app").setLevel(logging.DEBUG)


def flush_job_logs(timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    for handler in logging.getLogger().handlers:
        if isinstance(handler, JobLogHandler):
            while handler.pending.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.01)
