import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_runtime import repository, service
from app.modules.mcp_runtime.models import MCPRuntimeSession


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True


class FakeRuntimeManager:
    def provider_name(self, installation):
        return "local"

    def list_tools(self, installation):
        return []

    def call_tool(self, installation, *, tool_name, arguments):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}


class FailingRuntimeManager(FakeRuntimeManager):
    def call_tool(self, installation, *, tool_name, arguments):
        raise RuntimeError("tool failed")


def installed_server() -> tuple[MCPServerInstallation, MCPServerVersion]:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="remote",
        runtime_config={"kind": "remote"},
    )
    installation.id = uuid.uuid4()
    server = MCPServerVersion(
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools for forecasts",
        version="1.0.0",
        server_json={
            "name": "io.github.example/weather",
            "description": "Weather tools for forecasts",
            "version": "1.0.0",
        },
        status="active",
        status_message="",
        is_latest=True,
    )
    return installation, server


@pytest.mark.asyncio
async def test_call_tool_with_tracking_creates_session_and_invocation(monkeypatch) -> None:
    async def get_active_runtime_session(*args, **kwargs):
        return None

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)
    installation, server = installed_server()
    session = FakeSession()

    result = await service.call_tool_with_tracking(
        session,
        installation,
        server,
        tool_name="get_forecast",
        arguments={"location": "Delhi"},
        manager=FakeRuntimeManager(),
    )

    runtime_session = session.added[0]
    invocation = session.added[1]
    assert result["content"][0]["text"] == "ok"
    assert runtime_session.status == "idle"
    assert runtime_session.runtime_provider == "local"
    assert runtime_session.runtime_kind == "remote"
    assert invocation.status == "succeeded"
    assert invocation.tool_name == "get_forecast"
    assert invocation.input_size_bytes > 0
    assert invocation.output_size_bytes > 0
    assert session.flushed is True


@pytest.mark.asyncio
async def test_call_tool_with_tracking_records_failure(monkeypatch) -> None:
    async def get_active_runtime_session(*args, **kwargs):
        return None

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)
    installation, server = installed_server()
    session = FakeSession()

    with pytest.raises(RuntimeError, match="tool failed"):
        await service.call_tool_with_tracking(
            session,
            installation,
            server,
            tool_name="get_forecast",
            arguments={},
            manager=FailingRuntimeManager(),
        )

    runtime_session = session.added[0]
    invocation = session.added[1]
    assert runtime_session.status == "idle"
    assert runtime_session.failure_count == 1
    assert runtime_session.last_error == "tool failed"
    assert invocation.status == "failed"
    assert invocation.is_error is True
    assert invocation.error == "tool failed"


@pytest.mark.asyncio
async def test_reap_expired_runtime_sessions_marks_sessions_stopped(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now - timedelta(minutes=15),
        ready_at=now - timedelta(minutes=15),
        last_used_at=now - timedelta(minutes=15),
        expires_at=now - timedelta(minutes=1),
        stopped_at=None,
        failure_count=0,
        last_error="old",
    )

    async def list_expired_runtime_sessions(*args, **kwargs):
        return [runtime_session]

    monkeypatch.setattr(
        repository,
        "list_expired_runtime_sessions",
        list_expired_runtime_sessions,
    )
    result = await service.reap_expired_runtime_sessions(FakeSession())

    assert result.stopped_count == 1
    assert runtime_session.status == "stopped"
    assert runtime_session.stopped_at is not None
    assert runtime_session.last_error == ""
