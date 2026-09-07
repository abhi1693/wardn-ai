"""Shared, bounded text/JSON logging. Never pass input payloads as log fields."""

import json
import logging
import math
import re
import sys
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.core.http_logging import safe_request_url
from app.core.log_events import LEGACY_MESSAGES
from app.core.log_text import context_text, error_text, event_text, inline, local_time

_context: ContextVar[dict | None] = ContextVar("wardn_log_context", default=None)
_EVENT = re.compile(r"[a-z][a-z0-9_]{0,100}\Z")
_APP_LOGGERS = ("app.",)
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+")
# Explicit fields prevent accidental logging of request bodies, SQL or settings.
_FIELDS = frozenset(
    {
        "action",
        "agent_id",
        "agent_model_name",
        "agent_run_id",
        "agent_run_resume_job_id",
        "agent_scope",
        "api_token_has_expiry",
        "api_token_id",
        "api_token_is_active",
        "api_token_organization_scope_count",
        "api_token_updated_fields",
        "api_token_workspace_scope_count",
        "approval_id",
        "attempt",
        "chat_provider",
        "chat_provider_connection_id",
        "chat_provider_event_id",
        "chat_provider_slack_app_id",
        "chat_provider_slack_team_id",
        "chat_provider_source",
        "command",
        "command_id",
        "conversation_id",
        "duration_ms",
        "error_code",
        "error_type",
        "execution_id",
        "exit_code",
        "installation_id",
        "invitation_id",
        "job_id",
        "job_kind",
        "kubernetes_custom_network_policy_count",
        "kubernetes_discovery_method",
        "kubernetes_ingress_enabled",
        "kubernetes_network_policy_count",
        "kubernetes_replicas",
        "llm_credential_is_active",
        "llm_credential_updated_fields",
        "llm_provider_credential_id",
        "managed_secret_count",
        "managed_secret_id",
        "max_attempts",
        "mcp_catalog_affected_server_count",
        "mcp_catalog_auth_secret_handle_id",
        "mcp_catalog_batch_count",
        "mcp_catalog_batch_index",
        "mcp_catalog_batch_size",
        "mcp_catalog_batch_synced_count",
        "mcp_catalog_duplicate_count",
        "mcp_catalog_enabled",
        "mcp_catalog_http_status",
        "mcp_catalog_metadata_count",
        "mcp_catalog_pagination",
        "mcp_catalog_payload_count",
        "mcp_catalog_provider",
        "mcp_catalog_replaced_managed_secret_count",
        "mcp_catalog_retry_attempt",
        "mcp_catalog_retry_delay_seconds",
        "mcp_catalog_soft_deleted_version_count",
        "mcp_catalog_source_count",
        "mcp_catalog_source_id",
        "mcp_catalog_source_url_count",
        "mcp_catalog_sync_mode",
        "mcp_catalog_synced_count",
        "mcp_catalog_unique_count",
        "mcp_catalog_updated_fields",
        "mcp_catalog_updated_since",
        "mcp_catalog_without_metadata_count",
        "mcp_cleanup_path_count",
        "mcp_failed_installation_ids",
        "mcp_hub_submission_id",
        "mcp_install_status",
        "mcp_install_target",
        "mcp_install_type",
        "mcp_installation_id",
        "mcp_installation_new",
        "mcp_installation_update_count",
        "mcp_job_id",
        "mcp_job_progress_current",
        "mcp_job_progress_total",
        "mcp_operation",
        "mcp_refresh_failure_count",
        "mcp_registry_server_name",
        "mcp_registry_version",
        "mcp_registry_version_id",
        "mcp_runtime_control_action",
        "mcp_runtime_delete_resources",
        "mcp_runtime_health_status",
        "mcp_runtime_ready",
        "mcp_runtime_replace_reason",
        "mcp_runtime_session_count",
        "mcp_runtime_session_id",
        "mcp_secret_field_count",
        "mcp_server_count",
        "mcp_server_is_latest",
        "mcp_server_name",
        "mcp_server_version",
        "mcp_server_version_id",
        "mcp_server_was_deleted",
        "mcp_server_was_latest",
        "mcp_source_revision_expected",
        "mcp_telemetry_client",
        "mcp_tool_count",
        "mcp_tool_inventory_hash",
        "mcp_tool_invocation_id",
        "mcp_tool_name",
        "mcp_tool_proposal_status_code",
        "mcp_update_server_count",
        "mcp_update_target_count",
        "mcp_validation_error_present",
        "mcp_validation_error_type",
        "mcp_validation_status",
        "method",
        "organization_id",
        "organization_status",
        "phase",
        "provider_progress_state",
        "replacement_workspace_id",
        "request_id",
        "request_url",
        "retry_attempt",
        "retry_delay_seconds",
        "retryable",
        "return_code",
        "role",
        "route",
        "scheduled_task_id",
        "scheduled_task_run_id",
        "scope_type",
        "secret_handle_count",
        "secret_handle_id",
        "secret_handle_ids",
        "secret_handle_updated_fields",
        "secret_store_id",
        "secret_store_updated_fields",
        "secret_validation_ok",
        "secret_value_count",
        "service",
        "span_id",
        "status",
        "status_code",
        "tool_call_id",
        "trace_id",
        "updated_secret_handle_ids",
        "user_id",
        "worker_id",
        "worker_name",
        "workspace_id",
        "workspace_status",
    }
)


def log_identifier(value: UUID | str) -> str:
    """Keep request identifiers on one log line, even with a custom log handler."""
    return str(value).replace("\r", "").replace("\n", "")


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


@contextmanager
def log_context(**fields) -> Iterator[None]:
    """ContextVars also propagate from ASGI to FastAPI's synchronous thread pool."""
    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def safe_value(value, depth: int = 0):
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, str):
        # Request locations have a separate sanitizer; other fields never contain URLs.
        return _URL.sub("[redacted-url]", value)[:250]
    if isinstance(value, (list, tuple)) and depth < 3:
        return [safe_value(item, depth + 1) for item in value[:30]]
    return "[omitted]"


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self.payload(record), ensure_ascii=True, allow_nan=False)

    def payload(self, record: logging.LogRecord) -> dict:
        fields = {**(_context.get() or {}), **record.__dict__}
        event = (
            record.msg
            if (isinstance(record.msg, str) and (record.name or "").startswith(_APP_LOGGERS))
            else ""
        )
        message = None
        if event in LEGACY_MESSAGES:
            message = re.sub(r"%[-+#0-9.]*[sdrf]", "[omitted]", event)
            event = re.sub(r"[^a-z0-9]+", "_", message.casefold()).strip("_")[:100]
        elif not _EVENT.fullmatch(event):
            event = (
                "application_log"
                if (record.name or "").startswith(_APP_LOGGERS)
                else "dependency_log"
            )
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "event": event,
            "pid": record.process,
            **{
                key: safe_request_url(value)
                if key in {"route", "request_url"}
                else safe_value(value)
                for key, value in fields.items()
                if key in _FIELDS
            },
        }
        if message is not None:
            payload["message"] = message
        if payload["event"] in {"dependency_log", "application_log"}:
            # Library messages/arguments can contain SQL, HTTP query strings or RQ tracebacks.
            # Keep their origin, but never format their raw messages or arguments.
            payload["location"] = f"{record.module}.{record.funcName}:{record.lineno}"
        if record.exc_info and record.exc_info[1] is not None:
            payload["error_type"] = type(record.exc_info[1]).__name__
            payload["exception"] = exception_details(record.exc_info[1])
        return payload


class TextFormatter(JsonFormatter):
    def __init__(self, service: str, *, verbose: bool = False):
        super().__init__(service)
        self.verbose = verbose

    def format(self, record: logging.LogRecord) -> str:
        payload = self.payload(record)
        level = "WARN" if payload["level"] == "WARNING" else payload["level"]
        prefix = f"{local_time(payload['timestamp'])} {level:<5} [{inline(payload['service'])}]"
        message = event_text(payload)
        error = error_text(payload, verbose=self.verbose)
        if error:
            message += f" - {error}"
        details = context_text(payload, verbose=self.verbose)
        return f"{prefix} {message}" + (f" ({'; '.join(details)})" if details else "")

    def quiet(self, record: logging.LogRecord) -> bool:
        if self.verbose:
            return False
        if not (record.name or "").startswith(_APP_LOGGERS):
            return record.levelno < logging.WARNING
        return isinstance(record.msg, str) and record.msg in {
            "command_started",
            "command_completed",
            "command_succeeded",
        }


def exception_details(exc: BaseException | None) -> list[dict]:
    """Preserve exception types and stack locations, never messages, source or locals."""
    details: list[dict] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen and len(details) < 5:
        seen.add(id(exc))
        frames = []
        for frame, lineno in traceback.walk_tb(exc.__traceback__):
            frames.append(
                {
                    "file": Path(frame.f_code.co_filename).name,
                    "line": lineno,
                    "function": frame.f_code.co_name,
                }
            )
        detail = {"type": type(exc).__name__, "frames": frames[-30:]}
        if (
            isinstance(exc, NameError)
            and isinstance(exc.name, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exc.name)
        ):
            detail["missing_name"] = exc.name
        # Interpreter-supplied identifiers are useful without the exception
        # message or the object's repr/data. Bound both identifiers.
        if (
            isinstance(exc, AttributeError)
            and isinstance(exc.name, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exc.name)
        ):
            detail["attribute"] = exc.name
            owner = type(exc.obj).__name__
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", owner):
                detail["object_type"] = owner
        details.append(detail)
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return details


class StderrHandler(logging.StreamHandler):
    """Resolve stderr at emit time, including after CLI redirection or a worker fork."""

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(self.formatter, TextFormatter) and self.formatter.quiet(record):
            return
        self.stream = sys.stderr
        super().emit(record)

    def handleError(self, record: logging.LogRecord) -> None:
        # The stdlib fallback prints raw messages/arguments after formatting errors.
        # Never expose the failed record, including when the output stream is closed.
        with suppress(OSError, ValueError):
            sys.stderr.write("logging_error: unable to emit application log\n")


def configure_logging(
    service: str = "api", level: str | None = None, log_format: str | None = None
) -> None:
    """Configure one owned handler; preserve embedding and test handlers."""
    from app.core.config import get_settings

    settings = get_settings()
    level = (level or settings.log_level).upper()
    log_format = (log_format or settings.log_format).lower()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("invalid logging level")
    if log_format not in {"text", "json"}:
        raise ValueError("invalid logging format")
    root = logging.getLogger()
    handler = next((item for item in root.handlers if isinstance(item, StderrHandler)), None)
    if handler is None:
        handler = StderrHandler()
        root.addHandler(handler)
    handler.setFormatter(
        JsonFormatter(service)
        if log_format == "json"
        else TextFormatter(service, verbose=level == "DEBUG")
    )
    handler.setLevel(level)
    root.setLevel(level)
    logging.getLogger("app").setLevel(level)
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
    for name in ("uvicorn", "uvicorn.error", "alembic"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.disabled = False
        logger.setLevel(level)
    for name in ("httpcore", "httpx", "sqlalchemy", "urllib3", "websockets"):
        logging.getLogger(name).setLevel(logging.WARNING)

    if service != "migration":
        from app.modules.observability.job_logs import configure_job_log_capture

        configure_job_log_capture()
