import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_runtime import repository, service
from app.modules.mcp_runtime.models import (
    MCPRuntimeEvent,
    MCPRuntimeSession,
    MCPToolInvocation,
)
from app.modules.mcp_runtime.provider import RuntimeHealth


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
    fingerprint = "runtime-fingerprint"

    def __init__(self) -> None:
        self.stopped_sessions: list[MCPRuntimeSession] = []
        self.warmed_sessions: list[MCPRuntimeSession] = []
        self.wait_ready_values: list[bool] = []
        self.delete_resources_values: list[bool] = []

    def provider_name(self, installation):
        return "local"

    def runtime_spec(self, installation):
        return type(
            "RuntimeSpec",
            (),
            {
                "provider_name": "local",
                "runtime_kind": "remote",
                "endpoint_url": "",
                "fingerprint": lambda self: "runtime-fingerprint",
            },
        )()

    def runtime_fingerprint(self, installation):
        return self.fingerprint

    def list_tools(self, installation):
        return []

    def call_tool(self, installation, *, tool_name, arguments, runtime_session=None):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    def ensure_runtime(self, installation, *, runtime_session=None, wait_ready=True):
        if runtime_session is not None:
            self.warmed_sessions.append(runtime_session)
        self.wait_ready_values.append(wait_ready)
        return RuntimeHealth(
            status="ready",
            healthy=True,
            ready=True,
            message="Runtime is ready.",
        )

    def stop_runtime(self, runtime_session, *, delete_resources=False):
        self.stopped_sessions.append(runtime_session)
        self.delete_resources_values.append(delete_resources)

    def health_runtime(self, runtime_session):
        return RuntimeHealth(
            status="ready",
            healthy=True,
            ready=True,
            message="Runtime is ready.",
            details={"transport": "stdio"},
        )


class FailingRuntimeManager(FakeRuntimeManager):
    def call_tool(self, installation, *, tool_name, arguments, runtime_session=None):
        raise RuntimeError("tool failed")


class FailingStopRuntimeManager(FakeRuntimeManager):
    def stop_runtime(self, runtime_session, *, delete_resources=False):
        raise RuntimeError("stop failed")


class ThreadRecordingRuntimeManager(FakeRuntimeManager):
    def __init__(self) -> None:
        super().__init__()
        self.call_thread_id: int | None = None

    def call_tool(self, installation, *, tool_name, arguments, runtime_session=None):
        self.call_thread_id = threading.get_ident()
        return super().call_tool(
            installation,
            tool_name=tool_name,
            arguments=arguments,
            runtime_session=runtime_session,
        )


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


def added_one(session: FakeSession, model_type):
    return next(item for item in session.added if isinstance(item, model_type))


def added_events(session: FakeSession) -> list[MCPRuntimeEvent]:
    return [item for item in session.added if isinstance(item, MCPRuntimeEvent)]


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

    runtime_session = added_one(session, MCPRuntimeSession)
    invocation = added_one(session, MCPToolInvocation)
    event_types = [event.event_type for event in added_events(session)]
    assert result["content"][0]["text"] == "ok"
    assert runtime_session.status == "idle"
    assert runtime_session.runtime_provider == "local"
    assert runtime_session.runtime_kind == "remote"
    assert runtime_session.config_fingerprint == "runtime-fingerprint"
    assert invocation.status == "succeeded"
    assert invocation.tool_name == "get_forecast"
    assert invocation.input_size_bytes > 0
    assert invocation.output_size_bytes > 0
    assert event_types == [
        service.RUNTIME_EVENT_SESSION_CREATED,
        service.RUNTIME_EVENT_TOOL_CALL_STARTED,
        service.RUNTIME_EVENT_TOOL_CALL_SUCCEEDED,
    ]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_warm_runtime_session_ensures_runtime_and_records_events(monkeypatch) -> None:
    async def get_active_runtime_session(*args, **kwargs):
        return None

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)
    installation, _server = installed_server()
    session = FakeSession()
    manager = FakeRuntimeManager()
    now = datetime(2024, 1, 1, tzinfo=UTC)

    runtime_session = await service.warm_runtime_session(
        session,
        installation,
        manager=manager,
        now=now,
    )

    assert manager.warmed_sessions == [runtime_session]
    assert manager.wait_ready_values == [True]
    assert runtime_session.status == "idle"
    assert runtime_session.ready_at is not None
    assert runtime_session.last_error == ""
    assert [event.event_type for event in added_events(session)] == [
        service.RUNTIME_EVENT_SESSION_CREATED,
        service.RUNTIME_EVENT_WARMUP_STARTED,
        service.RUNTIME_EVENT_WARMUP_SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_warm_runtime_session_can_reconcile_without_waiting_ready(monkeypatch) -> None:
    async def get_active_runtime_session(*args, **kwargs):
        return None

    class NotWaitingRuntimeManager(FakeRuntimeManager):
        def ensure_runtime(self, installation, *, runtime_session=None, wait_ready=True):
            if runtime_session is not None:
                self.warmed_sessions.append(runtime_session)
            self.wait_ready_values.append(wait_ready)
            return RuntimeHealth(
                status="not_ready",
                healthy=True,
                ready=False,
                message="Runtime reconciled.",
            )

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)
    installation, _server = installed_server()
    session = FakeSession()
    manager = NotWaitingRuntimeManager()

    runtime_session = await service.warm_runtime_session(
        session,
        installation,
        manager=manager,
        wait_ready=False,
    )

    assert manager.warmed_sessions == [runtime_session]
    assert manager.wait_ready_values == [False]
    assert runtime_session.status == "idle"
    assert runtime_session.ready_at is None
    assert runtime_session.last_error == ""


@pytest.mark.asyncio
async def test_call_tool_with_tracking_runs_runtime_call_off_event_loop(monkeypatch) -> None:
    async def get_active_runtime_session(*args, **kwargs):
        return None

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)
    installation, server = installed_server()
    session = FakeSession()
    manager = ThreadRecordingRuntimeManager()
    event_loop_thread_id = threading.get_ident()

    result = await service.call_tool_with_tracking(
        session,
        installation,
        server,
        tool_name="get_forecast",
        arguments={"location": "Delhi"},
        manager=manager,
    )

    assert result["content"][0]["text"] == "ok"
    assert manager.call_thread_id is not None
    assert manager.call_thread_id != event_loop_thread_id


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

    runtime_session = added_one(session, MCPRuntimeSession)
    invocation = added_one(session, MCPToolInvocation)
    event_types = [event.event_type for event in added_events(session)]
    assert runtime_session.status == "idle"
    assert runtime_session.failure_count == 1
    assert runtime_session.last_error == "tool failed"
    assert invocation.status == "failed"
    assert invocation.is_error is True
    assert invocation.error == "tool failed"
    assert event_types == [
        service.RUNTIME_EVENT_SESSION_CREATED,
        service.RUNTIME_EVENT_TOOL_CALL_STARTED,
        service.RUNTIME_EVENT_TOOL_CALL_FAILED,
    ]


@pytest.mark.asyncio
async def test_ensure_runtime_session_reuses_matching_fingerprint(monkeypatch) -> None:
    installation, server = installed_server()
    session = FakeSession()
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=installation.id,
        server_name=server.name,
        server_version=server.version,
        runtime_provider="local",
        runtime_kind="remote",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now,
        ready_at=now,
        last_used_at=now,
        expires_at=now + timedelta(minutes=5),
        stopped_at=None,
        failure_count=0,
        last_error="old",
    )
    runtime_session.id = uuid.uuid4()

    async def get_active_runtime_session(*args, **kwargs):
        return runtime_session

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)

    manager = FakeRuntimeManager()

    result = await service.ensure_runtime_session(
        session,
        installation,
        server,
        manager=manager,
        now=now,
    )

    assert result is runtime_session
    assert runtime_session.status == "running"
    assert runtime_session.last_error == ""
    event = added_one(session, MCPRuntimeEvent)
    assert event.event_type == service.RUNTIME_EVENT_SESSION_REUSED
    assert manager.stopped_sessions == []


@pytest.mark.asyncio
async def test_ensure_runtime_session_replaces_changed_fingerprint(monkeypatch) -> None:
    installation, server = installed_server()
    session = FakeSession()
    now = datetime.now(UTC)
    old_runtime_session = MCPRuntimeSession(
        installation_id=installation.id,
        server_name=server.name,
        server_version=server.version,
        runtime_provider="local",
        runtime_kind="remote",
        config_fingerprint="old-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now,
        ready_at=now,
        last_used_at=now,
        expires_at=now + timedelta(minutes=5),
        stopped_at=None,
        failure_count=0,
        last_error="",
    )
    old_runtime_session.id = uuid.uuid4()

    async def get_active_runtime_session(*args, **kwargs):
        return old_runtime_session

    monkeypatch.setattr(repository, "get_active_runtime_session", get_active_runtime_session)

    manager = FakeRuntimeManager()

    result = await service.ensure_runtime_session(
        session,
        installation,
        server,
        manager=manager,
        now=now,
    )

    assert manager.stopped_sessions == [old_runtime_session]
    assert old_runtime_session.status == "stopped"
    assert old_runtime_session.stopped_at == now
    assert result is added_one(session, MCPRuntimeSession)
    assert result.config_fingerprint == "runtime-fingerprint"
    assert [event.event_type for event in added_events(session)] == [
        service.RUNTIME_EVENT_SESSION_REPLACED,
        service.RUNTIME_EVENT_SESSION_CREATED,
    ]


@pytest.mark.asyncio
async def test_reap_expired_runtime_sessions_marks_sessions_stopped(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
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
    runtime_session.id = uuid.uuid4()

    async def list_expired_runtime_sessions(*args, **kwargs):
        return [runtime_session]

    monkeypatch.setattr(
        repository,
        "list_expired_runtime_sessions",
        list_expired_runtime_sessions,
    )
    manager = FakeRuntimeManager()
    session = FakeSession()
    result = await service.reap_expired_runtime_sessions(session, manager=manager)

    assert manager.stopped_sessions == [runtime_session]
    assert manager.delete_resources_values == [False]
    assert result.stopped_count == 1
    assert runtime_session.status == "stopped"
    assert runtime_session.stopped_at is not None
    assert runtime_session.last_error == ""
    assert added_one(session, MCPRuntimeEvent).event_type == service.RUNTIME_EVENT_REAPER_STOPPED


@pytest.mark.asyncio
async def test_shutdown_active_runtime_sessions_stops_active_sessions(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now - timedelta(minutes=5),
        ready_at=now - timedelta(minutes=5),
        last_used_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        stopped_at=None,
        failure_count=0,
        last_error="old",
    )
    runtime_session.id = uuid.uuid4()

    async def list_active_runtime_sessions(*args, **kwargs):
        return [runtime_session] if runtime_session.status == "idle" else []

    monkeypatch.setattr(
        repository,
        "list_active_runtime_sessions",
        list_active_runtime_sessions,
    )
    manager = FakeRuntimeManager()
    session = FakeSession()

    result = await service.shutdown_active_runtime_sessions(session, manager=manager)

    assert manager.stopped_sessions == [runtime_session]
    assert manager.delete_resources_values == [True]
    assert result.stopped_count == 1
    assert result.failed_count == 0
    assert runtime_session.status == "stopped"
    assert runtime_session.stopped_at is not None
    assert runtime_session.expires_at == runtime_session.stopped_at
    assert runtime_session.last_error == ""
    assert added_one(session, MCPRuntimeEvent).event_type == service.RUNTIME_EVENT_SESSION_STOPPED


@pytest.mark.asyncio
async def test_shutdown_active_runtime_sessions_marks_stop_failures(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now - timedelta(minutes=5),
        ready_at=now - timedelta(minutes=5),
        last_used_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        stopped_at=None,
        failure_count=0,
        last_error="old",
    )
    runtime_session.id = uuid.uuid4()

    async def list_active_runtime_sessions(*args, **kwargs):
        return [runtime_session] if runtime_session.status == "idle" else []

    monkeypatch.setattr(
        repository,
        "list_active_runtime_sessions",
        list_active_runtime_sessions,
    )
    session = FakeSession()

    result = await service.shutdown_active_runtime_sessions(
        session,
        manager=FailingStopRuntimeManager(),
    )

    assert result.stopped_count == 0
    assert result.failed_count == 1
    assert runtime_session.status == "failed"
    assert runtime_session.failure_count == 1
    assert runtime_session.last_error == "stop failed"
    assert added_one(session, MCPRuntimeEvent).event_type == (
        service.RUNTIME_EVENT_SHUTDOWN_STOP_FAILED
    )


@pytest.mark.asyncio
async def test_stop_runtime_session_stops_active_session(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now - timedelta(minutes=5),
        ready_at=now - timedelta(minutes=5),
        last_used_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        stopped_at=None,
        failure_count=0,
        last_error="old",
    )
    runtime_session.id = uuid.uuid4()

    async def get_runtime_session(*args, **kwargs):
        return runtime_session

    monkeypatch.setattr(repository, "get_runtime_session", get_runtime_session)
    manager = FakeRuntimeManager()
    session = FakeSession()

    response = await service.stop_runtime_session(
        session,
        runtime_session.id,
        manager=manager,
    )

    assert manager.stopped_sessions == [runtime_session]
    assert runtime_session.status == "stopped"
    assert runtime_session.stopped_at is not None
    assert runtime_session.expires_at == runtime_session.stopped_at
    assert runtime_session.last_error == ""
    assert response.status == "stopped"
    assert added_one(session, MCPRuntimeEvent).event_type == service.RUNTIME_EVENT_SESSION_STOPPED


@pytest.mark.asyncio
async def test_stop_runtime_session_is_idempotent_for_stopped_session(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="stopped",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now - timedelta(minutes=5),
        ready_at=now - timedelta(minutes=5),
        last_used_at=now - timedelta(minutes=1),
        expires_at=now,
        stopped_at=now,
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    async def get_runtime_session(*args, **kwargs):
        return runtime_session

    monkeypatch.setattr(repository, "get_runtime_session", get_runtime_session)
    manager = FakeRuntimeManager()

    response = await service.stop_runtime_session(
        FakeSession(),
        runtime_session.id,
        manager=manager,
    )

    assert manager.stopped_sessions == []
    assert response.status == "stopped"


@pytest.mark.asyncio
async def test_get_runtime_session_health_uses_manager_and_scope(monkeypatch) -> None:
    now = datetime.now(UTC)
    workspace_id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        started_at=now,
        ready_at=now,
        last_used_at=now,
        expires_at=now + timedelta(minutes=5),
        stopped_at=None,
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    seen = {}

    async def get_runtime_session(session, runtime_session_id, *, workspace_id=None):
        seen["runtime_session_id"] = runtime_session_id
        seen["workspace_id"] = workspace_id
        return runtime_session

    monkeypatch.setattr(repository, "get_runtime_session", get_runtime_session)

    response = await service.get_runtime_session_health(
        FakeSession(),
        runtime_session.id,
        workspace_id=workspace_id,
        manager=FakeRuntimeManager(),
    )

    assert seen == {
        "runtime_session_id": runtime_session.id,
        "workspace_id": workspace_id,
    }
    assert response.runtime_session_id == runtime_session.id
    assert response.status == "ready"
    assert response.healthy is True
    assert response.ready is True
    assert response.details == {"transport": "stdio"}


@pytest.mark.asyncio
async def test_list_runtime_events_checks_session_scope(monkeypatch) -> None:
    now = datetime.now(UTC)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    runtime_event = MCPRuntimeEvent(
        runtime_session_id=runtime_session.id,
        event_type=service.RUNTIME_EVENT_SESSION_CREATED,
        message="Runtime session created.",
        event_metadata={"runtimeProvider": "local"},
        created_at=now,
        updated_at=now,
    )
    runtime_event.id = uuid.uuid4()
    seen = {}

    async def get_runtime_session(session, runtime_session_id, *, workspace_id=None):
        seen["workspace_id"] = workspace_id
        return runtime_session

    async def list_runtime_events(session, runtime_session_id, *, limit=100):
        seen["runtime_session_id"] = runtime_session_id
        seen["limit"] = limit
        return [runtime_event]

    monkeypatch.setattr(repository, "get_runtime_session", get_runtime_session)
    monkeypatch.setattr(repository, "list_runtime_events", list_runtime_events)
    workspace_id = uuid.uuid4()

    response = await service.list_runtime_events(
        FakeSession(),
        runtime_session.id,
        workspace_id=workspace_id,
        limit=25,
    )

    assert seen == {
        "workspace_id": workspace_id,
        "runtime_session_id": runtime_session.id,
        "limit": 25,
    }
    assert response.events[0].event_type == service.RUNTIME_EVENT_SESSION_CREATED
    assert response.events[0].metadata == {"runtimeProvider": "local"}


@pytest.mark.asyncio
async def test_get_runtime_summary_aggregates_runtime_health(monkeypatch) -> None:
    now = datetime.now(UTC)
    workspace_id = uuid.uuid4()
    error_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=3,
        last_error="tool failed",
    )
    error_session.id = uuid.uuid4()
    error_session.updated_at = now
    duplicate_error_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="package",
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=1,
        last_error="older error",
    )
    duplicate_error_session.id = uuid.uuid4()
    duplicate_error_session.updated_at = now - timedelta(minutes=5)
    seen = {}

    async def count_runtime_sessions_by_status(session, *, workspace_id=None):
        seen["status_workspace_id"] = workspace_id
        return {"idle": 2, "running": 1, "failed": 1, "stopped": 4, "expired": 1}

    async def count_stale_active_runtime_sessions(session, *, workspace_id=None, now=None):
        seen["stale_workspace_id"] = workspace_id
        seen["now"] = now
        return 1

    async def count_tool_invocations(session, *, workspace_id=None, started_since=None):
        seen.setdefault("tool_calls", []).append((workspace_id, started_since))
        if started_since is None:
            return [("succeeded", False, 7), ("succeeded", True, 1), ("failed", False, 2)]
        return [("succeeded", False, 3), ("failed", False, 1)]

    async def list_recent_error_runtime_sessions(session, *, workspace_id=None, limit=50):
        seen["error_workspace_id"] = workspace_id
        seen["error_limit"] = limit
        return [error_session, duplicate_error_session]

    monkeypatch.setattr(
        repository,
        "count_runtime_sessions_by_status",
        count_runtime_sessions_by_status,
    )
    monkeypatch.setattr(
        repository,
        "count_stale_active_runtime_sessions",
        count_stale_active_runtime_sessions,
    )
    monkeypatch.setattr(repository, "count_tool_invocations", count_tool_invocations)
    monkeypatch.setattr(
        repository,
        "list_recent_error_runtime_sessions",
        list_recent_error_runtime_sessions,
    )

    response = await service.get_runtime_summary(
        FakeSession(),
        workspace_id=workspace_id,
        now=now,
    )

    assert response.total_sessions == 9
    assert response.active_sessions == 3
    assert response.idle_sessions == 2
    assert response.failed_sessions == 1
    assert response.stopped_sessions == 4
    assert response.expired_sessions == 1
    assert response.stale_active_sessions == 1
    assert response.tool_calls.total == 10
    assert response.tool_calls.succeeded == 7
    assert response.tool_calls.failed == 3
    assert response.tool_calls.recent_total == 4
    assert response.tool_calls.recent_failed == 1
    assert response.tool_calls.recent_failure_rate == 0.25
    assert len(response.recent_server_errors) == 1
    assert response.recent_server_errors[0].last_error == "tool failed"
    assert seen["status_workspace_id"] == workspace_id
    assert seen["stale_workspace_id"] == workspace_id
    assert seen["error_workspace_id"] == workspace_id
    assert seen["tool_calls"][0] == (workspace_id, None)
    assert seen["tool_calls"][1][0] == workspace_id
    assert seen["tool_calls"][1][1] == now - service.RUNTIME_SUMMARY_RECENT_WINDOW


@pytest.mark.asyncio
async def test_prune_runtime_events_deletes_events_before_cutoff(monkeypatch) -> None:
    now = datetime.now(UTC)
    seen = {}

    async def delete_runtime_events_before(session, *, cutoff):
        seen["session"] = session
        seen["cutoff"] = cutoff
        return 4

    monkeypatch.setattr(
        repository,
        "delete_runtime_events_before",
        delete_runtime_events_before,
    )
    fake_session = FakeSession()

    deleted_count = await service.prune_runtime_events(
        fake_session,
        retention_days=14,
        now=now,
    )

    assert deleted_count == 4
    assert seen == {
        "session": fake_session,
        "cutoff": now - timedelta(days=14),
    }


@pytest.mark.asyncio
async def test_prune_runtime_events_can_be_disabled(monkeypatch) -> None:
    async def delete_runtime_events_before(*args, **kwargs):
        raise AssertionError("disabled retention should not delete events")

    monkeypatch.setattr(
        repository,
        "delete_runtime_events_before",
        delete_runtime_events_before,
    )

    deleted_count = await service.prune_runtime_events(
        FakeSession(),
        retention_days=0,
    )

    assert deleted_count == 0


@pytest.mark.asyncio
async def test_prune_tool_invocations_deletes_invocations_before_cutoff(monkeypatch) -> None:
    now = datetime.now(UTC)
    seen = {}

    async def delete_tool_invocations_before(session, *, cutoff):
        seen["session"] = session
        seen["cutoff"] = cutoff
        return 6

    monkeypatch.setattr(
        repository,
        "delete_tool_invocations_before",
        delete_tool_invocations_before,
    )
    fake_session = FakeSession()

    deleted_count = await service.prune_tool_invocations(
        fake_session,
        retention_days=30,
        now=now,
    )

    assert deleted_count == 6
    assert seen == {
        "session": fake_session,
        "cutoff": now - timedelta(days=30),
    }


@pytest.mark.asyncio
async def test_prune_tool_invocations_can_be_disabled(monkeypatch) -> None:
    async def delete_tool_invocations_before(*args, **kwargs):
        raise AssertionError("disabled retention should not delete tool invocations")

    monkeypatch.setattr(
        repository,
        "delete_tool_invocations_before",
        delete_tool_invocations_before,
    )

    deleted_count = await service.prune_tool_invocations(
        FakeSession(),
        retention_days=0,
    )

    assert deleted_count == 0
