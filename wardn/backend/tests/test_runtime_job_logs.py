import asyncio
import json
import logging
import threading
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from app.core.logging import log_context
from app.db.session import get_db_session
from app.modules.observability import job_log_router, job_log_service
from app.modules.observability.job_logs import (
    MAX_EVENT_BYTES,
    JobLogHandler,
    encode_record,
    logged_agent_stream,
    logged_job,
)
from app.modules.users.dependencies import get_current_user

ORG = uuid.uuid4()
JOB = uuid.uuid4()


def entry_record():
    return logging.makeLogRecord(
        {
            "name": "app.tests.logs",
            "msg": "test_event",
            "levelname": "INFO",
            "levelno": logging.INFO,
            "job_kind": "mcp_operation",
            "job_id": str(JOB),
            "organization_id": str(ORG),
            "arguments": {"token": "private-token"},
        }
    )


def test_only_scoped_sanitized_bounded_records_are_queued():
    entry = encode_record(entry_record())
    assert entry["job_id"] == str(JOB)
    assert entry["organization_id"] == str(ORG)
    encoded = json.dumps(entry["entry"])
    assert "private-token" not in encoded and len(encoded) < MAX_EVENT_BYTES
    record = entry_record()
    record.organization_id = "not-a-uuid"
    assert encode_record(record) is None


def test_capture_is_nonblocking_and_flushes_independently_of_operation_failure():
    entered, release = threading.Event(), threading.Event()
    written = []

    def writer(batch):
        entered.set()
        release.wait(2)
        written.extend(batch)

    handler = JobLogHandler(writer)
    handler.emit(entry_record())
    assert entered.wait(1)
    # The first write is blocked, but the calling thread can enqueue another.
    handler.emit(entry_record())
    assert handler.pending.qsize() == 1
    release.set()
    handler.close()
    assert len(written) == 2


def test_storage_failure_does_not_raise_or_expose_credentials(caplog):
    attempts = []

    def writer(batch):
        attempts.append(batch)
        raise RuntimeError("postgresql://private-password@database/secret")

    handler = JobLogHandler(writer)
    handler.emit(entry_record())
    handler.close()
    assert attempts and handler.retry_at > 0
    assert "private-password" not in caplog.text


@pytest.mark.asyncio
async def test_nested_job_context_isolated_across_tasks_and_threads():
    @logged_job("scheduled_task")
    async def run(job, *, worker_id):
        await asyncio.sleep(0)
        return await asyncio.to_thread(
            lambda: encode_record(
                logging.makeLogRecord(
                    {"name": "app.tests.logs", "msg": "thread_event", "levelname": "DEBUG"}
                )
            )
        )

    first = SimpleNamespace(id=JOB, organization_id=ORG, workspace_id=None, attempt_count=2)
    second = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4(), workspace_id=None)
    results = await asyncio.gather(run(first, worker_id="one"), run(job=second, worker_id="two"))
    assert results[0]["job_id"] == str(first.id)
    assert results[1]["organization_id"] == str(second.organization_id)
    assert results[0]["entry"]["fields"]["attempt"] == 2
    assert encode_record(logging.makeLogRecord({"name": "app.tests", "msg": "outside"})) is None


@pytest.mark.asyncio
async def test_agent_stream_context_resets_between_yields_and_on_close():
    captured = []

    @logged_agent_stream
    async def stream(*, agent_run):
        try:
            for _ in range(2):
                captured.append(
                    encode_record(
                        logging.makeLogRecord(
                            {"name": "app.tests", "msg": "inside_event", "levelname": "INFO"}
                        )
                    )
                )
                yield "private-model-text"
        finally:
            captured.append(
                encode_record(
                    logging.makeLogRecord(
                        {"name": "app.tests", "msg": "closing_event", "levelname": "INFO"}
                    )
                )
            )

    run = SimpleNamespace(
        id=JOB, organization_id=ORG, workspace_id=uuid.uuid4(), agent_id=uuid.uuid4()
    )
    generator = stream(agent_run=run)
    with log_context(request_id="outer"):
        await anext(generator)
        assert encode_record(logging.makeLogRecord({"name": "app.tests", "msg": "outside"})) is None
        await generator.aclose()
    assert len(captured) == 2
    assert all(item["job_id"] == str(JOB) for item in captured)
    assert "private-model-text" not in json.dumps(captured)


class ReadSession:
    def __init__(self, *, rows=(), count=0, job=None):
        self.rows, self.count, self.job = rows, count, job
        self.statements = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return self.rows

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.job if self.job is not None else self.count


@pytest.mark.asyncio
async def test_reader_uses_exclusive_cursor_scope_expiry_and_skips_invalid_rows():
    entry = encode_record(entry_record())["entry"]
    session = ReadSession(
        rows=[
            SimpleNamespace(id=11, entry={}),
            SimpleNamespace(id=12, entry=entry),
            SimpleNamespace(id=13, entry=entry),
        ],
        count=3,
    )
    result = await job_log_service.read_logs(
        session, ORG, "mcp_operation", SimpleNamespace(id=JOB, status="running"), after=10, limit=2
    )
    assert result.next_cursor == "12" and result.has_more
    assert result.unreadable_entries == 1
    assert [item.id for item in result.items] == ["12"]
    query = session.statements[0].compile(dialect=postgresql.dialect())
    assert "runtime_job_logs.id >" in str(query)
    assert "runtime_job_logs.expires_at > now()" in str(query)
    assert ORG in query.params.values() and JOB in query.params.values()


@pytest.mark.asyncio
async def test_storage_outage_is_not_empty_history():
    class Unavailable(ReadSession):
        async def scalars(self, statement):
            raise OperationalError("query", {}, RuntimeError("private-password"))

    with pytest.raises(HTTPException) as caught:
        await job_log_service.read_logs(
            Unavailable(),
            ORG,
            "mcp_operation",
            SimpleNamespace(id=JOB, status="failed"),
            after=None,
            limit=100,
        )
    assert caught.value.status_code == 503 and "private" not in caught.value.detail


@pytest.mark.parametrize("allowed", [True, False])
def test_logs_endpoint_requires_admin_and_sends_no_store(monkeypatch, allowed):
    called = []
    app = FastAPI()
    app.include_router(job_log_router.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[get_db_session] = lambda: ReadSession()

    async def authorize(session, user, organization_id):
        assert organization_id == ORG
        if not allowed:
            raise HTTPException(403, "Forbidden")

    async def get_job(session, organization_id, kind, job_id):
        called.append((organization_id, kind, job_id))
        return SimpleNamespace(id=job_id, status="succeeded")

    monkeypatch.setattr(job_log_router, "require_organization_admin_or_404", authorize)
    monkeypatch.setattr(job_log_service, "get_log_job", get_job)
    response = TestClient(app).get(f"/organizations/{ORG}/runtime-logs/mcp_operation/{JOB}")
    assert response.status_code == (200 if allowed else 403)
    if allowed:
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["jobId"] == str(JOB)
        assert called == [(ORG, "mcp_operation", JOB)]
    else:
        assert not called


@pytest.mark.asyncio
async def test_cross_organization_job_lookup_is_scoped():
    session = ReadSession(count=None)
    with pytest.raises(HTTPException) as caught:
        await job_log_service.get_log_job(session, ORG, "mcp_operation", JOB)
    assert caught.value.status_code == 404
    query = session.statements[0].compile(dialect=postgresql.dialect())
    assert ORG in query.params.values() and JOB in query.params.values()
