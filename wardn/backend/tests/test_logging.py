import asyncio
import json
import logging
import runpy
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from app.api.http_errors import configure_error_handling
from app.api.request_id import RequestIDMiddleware
from app.core.config import Settings
from app.core.http_logging import safe_request_url
from app.core.logging import (
    JsonFormatter,
    StderrHandler,
    TextFormatter,
    configure_logging,
    log_context,
)

logger = logging.getLogger("app.tests.logging")


@pytest.fixture(autouse=True)
def logging_state(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: Settings(job_logs_enabled=False))
    loggers = [logging.getLogger()] + [
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    ]
    state = [
        (item, item.level, item.handlers[:], item.propagate, item.disabled) for item in loggers
    ]
    handlers = [
        (handler, handler.level, handler.formatter) for item in loggers for handler in item.handlers
    ]
    yield
    for item, level, saved, propagate, disabled in state:
        item.setLevel(level)
        item.handlers[:] = saved
        item.propagate, item.disabled = propagate, disabled
    for handler, level, formatter in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)


@pytest.mark.parametrize("formatter", [JsonFormatter, TextFormatter])
def test_safe_diagnostics_keep_ids_without_messages_payloads_or_sql(formatter):
    try:
        try:
            raise ValueError("postgresql://operator:private-password@database/app")
        except ValueError as cause:
            raise RuntimeError("SELECT private-body; token=private-token") from cause
    except RuntimeError:
        record = logging.LogRecord(
            "app.tests.logging", logging.ERROR, __file__, 10, "operation_failed", (), sys.exc_info()
        )
    record.organization_id = uuid.uuid4()
    record.arguments = {"password": "private-password"}
    record.authorization = "private-token"
    renderer = formatter("api", verbose=True) if formatter is TextFormatter else formatter("api")
    with log_context(request_id="request-123"):
        output = renderer.format(record)
    assert "operation_failed" in output and "request-123" in output
    assert str(record.organization_id) in output
    assert "RuntimeError" in output and "ValueError" in output
    assert "private-" not in output and "SELECT" not in output
    assert len(output.splitlines()) == 1


@pytest.mark.parametrize("name", ["httpx", "sqlalchemy.engine", "app.tests.logging"])
def test_unrecognized_messages_and_legacy_arguments_are_never_interpolated(name):
    record = logging.makeLogRecord(
        {"name": name, "msg": "private-password %s", "args": ("private-body",)}
    )
    assert "private" not in JsonFormatter("worker").format(record)
    record.name = "app.modules.mcp_registry.commands"
    record.msg = "MCP registry sync failed: %s"
    assert "private" not in JsonFormatter("worker").format(record)
    assert "MCP registry sync failed" in TextFormatter("worker").format(record)


def test_bounded_fields_and_formatter_failure_never_leak_raw_records(capsys):
    record = logging.makeLogRecord(
        {
            "name": "app.tests.logging",
            "msg": "safe_event",
            "worker_id": "worker\nforged",
            "duration_ms": float("nan"),
        }
    )
    cyclic = []
    cyclic.append(cyclic)
    record.secret_handle_ids = cyclic
    output = JsonFormatter("worker").format(record)
    assert len(output.splitlines()) == 1
    assert "[omitted]" in output
    assert json.loads(output)["duration_ms"] is None

    class BrokenFormatter(logging.Formatter):
        def format(self, record):
            raise RuntimeError("private-password")

    handler = StderrHandler()
    handler.setFormatter(BrokenFormatter())
    handler.handle(record)
    assert capsys.readouterr().err == "logging_error: unable to emit application log\n"


def test_idempotent_configuration_stderr_levels_and_library_noise(capsys):
    configure_logging("cli", "WARNING", "text")
    configure_logging("cli", "WARNING", "text")
    logger.info("hidden_event")
    logger.warning("visible_event", extra={"duration_ms": 12.5})
    output = capsys.readouterr()
    assert output.out == ""
    assert "[cli] Visible event" in output.err and "12 ms" in output.err
    assert "Hidden event" not in output.err
    assert sum(isinstance(item, StderrHandler) for item in logging.getLogger().handlers) == 1
    configure_logging("worker", "DEBUG", "json")
    assert logging.getLogger("uvicorn.access").disabled
    assert logging.getLogger("httpx").level == logging.WARNING


def test_settings_validate_format_and_case_insensitive_levels():
    assert Settings(log_level="debug", log_format="JSON").log_format == "json"
    for values in [{"log_format": "xml"}, {"log_level": "TRACE"}, {"job_log_max_entries": 99}]:
        with pytest.raises(ValidationError):
            Settings(**values)


def test_name_errors_and_job_progress_preserve_safe_actionable_diagnostics():
    error = NameError("private-error-message", name="activated_version_count")
    record = logging.LogRecord(
        "app.tests.logging",
        logging.ERROR,
        __file__,
        10,
        "operation_failed",
        (),
        (NameError, error, None),
    )
    output = TextFormatter("worker").format(record)
    assert "activated_version_count is not defined" in output
    assert "private-error" not in output
    record = logging.makeLogRecord(
        {
            "name": "app.tests.logging",
            "msg": "MCP operation job progress: %s",
            "args": ("private-progress",),
            "mcp_job_progress_current": 4,
            "mcp_job_progress_total": 10,
        }
    )
    output = TextFormatter("worker").format(record)
    assert "4/10" in output and "private-progress" not in output


def test_urls_preserve_locations_but_redact_credentials_queries_and_invitation_tokens():
    url = safe_request_url(
        "https://user:private-password@example.com/api/v1/items/123?limit=50&q=private-query&token=private-token#private-fragment"
    )
    assert "items/123?limit=50" in url and "q=[redacted]" in url
    assert "private" not in url and "user:" not in url
    assert "private-token" not in safe_request_url("/api/v1/invitations/private-token/accept")
    assert "private-token" not in safe_request_url("/invitations/private-token")


def test_failed_migration_exits_without_alembic_printing_raw_exception(monkeypatch, capsys):
    import sqlalchemy
    from alembic import context

    monkeypatch.setattr(
        context,
        "config",
        SimpleNamespace(
            config_ini_section="alembic",
            get_section=lambda *args: {},
        ),
        raising=False,
    )
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)

    def unavailable(*args, **kwargs):
        raise RuntimeError("SELECT private-payload; password=private-password")

    monkeypatch.setattr(sqlalchemy, "engine_from_config", unavailable)
    environment = Path(__file__).parents[1] / "app/db/migrations/env.py"
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(environment))
    assert caught.value.code == 1
    output = capsys.readouterr().err
    assert "Migration failed" in output and "RuntimeError" in output
    assert "private-" not in output and "Traceback" not in output


def test_request_context_covers_sync_handlers_streams_and_failures(capsys):
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    configure_error_handling(app)

    @app.get("/sync")
    def sync():
        logger.info("sync_event")
        return {"ok": True}

    @app.get("/stream")
    async def stream():
        async def body():
            logger.info("stream_first")
            yield "first"
            await asyncio.sleep(0)
            logger.info("stream_last")
            yield "last"

        return StreamingResponse(body())

    @app.get("/fail")
    async def fail():
        raise RuntimeError("private-error")

    configure_logging("api", "INFO", "json")
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ("/sync", "/stream", "/fail"):
            response = client.get(path + "?token=private-token")
            records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
            assert records[-1]["event"] == "request_completed"
            assert records[-1]["status_code"] == response.status_code
            assert all(
                record["request_id"] == response.headers["x-request-id"] for record in records
            )
            assert "private" not in json.dumps(records)
            if path == "/fail":
                assert sum(record["event"] == "request_failed" for record in records) == 1
                assert records[0]["exception"]
            if path == "/stream":
                assert [record["event"] for record in records] == [
                    "stream_first",
                    "stream_last",
                    "request_completed",
                ]


@pytest.mark.asyncio
async def test_context_does_not_leak_between_concurrent_tasks():
    async def task(identifier):
        with log_context(request_id=identifier):
            await asyncio.sleep(0)
            return JsonFormatter("api").payload(logging.makeLogRecord({"msg": "test"}))

    first, second = await asyncio.gather(task("first"), task("second"))
    assert first["request_id"] == "first" and second["request_id"] == "second"
    assert "request_id" not in JsonFormatter("api").payload(logging.makeLogRecord({"msg": "test"}))
