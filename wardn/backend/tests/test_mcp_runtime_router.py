import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.mcp_runtime import router as runtime_router
from app.modules.mcp_runtime import service as runtime_service
from app.modules.mcp_runtime.exceptions import MCPRuntimeSessionNotFoundError
from app.modules.mcp_runtime.schemas import (
    MCPRuntimeEventListResponse,
    MCPRuntimeEventRead,
    MCPRuntimeSessionHealthResponse,
    MCPRuntimeSessionListResponse,
    MCPRuntimeSessionRead,
    MCPRuntimeSummaryResponse,
    MCPRuntimeToolCallSummary,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

TEST_ORGANIZATION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEST_WORKSPACE_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


class FakeSession:
    committed = False

    async def commit(self):
        self.committed = True


async def fake_session():
    yield FakeSession()


async def fake_current_user():
    return User(id=uuid.uuid4(), email="admin@example.com", is_superuser=True)


async def fake_require_workspace_member(*args, **kwargs):
    return None


async def fake_require_workspace_admin(*args, **kwargs):
    return None


def workspace_runtime_path(suffix: str = "") -> str:
    return (
        f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/workspaces/{TEST_WORKSPACE_ID}"
        f"/mcp/runtime{suffix}"
    )


def runtime_session_read(
    *,
    workspace_id: uuid.UUID | None = None,
    status: str = "idle",
) -> MCPRuntimeSessionRead:
    now = datetime(2026, 6, 22, tzinfo=UTC)
    return MCPRuntimeSessionRead(
        id=uuid.uuid4(),
        organizationId=None,
        workspaceId=workspace_id,
        installationId=uuid.uuid4(),
        serverName="io.github.example/weather",
        serverVersion="1.0.0",
        runtimeProvider="local",
        runtimeKind="package",
        status=status,
        podName="",
        namespace="wardn-runtimes",
        startedAt=now,
        readyAt=now,
        lastUsedAt=now,
        expiresAt=now,
        stoppedAt=None,
        failureCount=0,
        lastError="",
    )


def runtime_event_read(runtime_session_id: uuid.UUID) -> MCPRuntimeEventRead:
    return MCPRuntimeEventRead(
        id=uuid.uuid4(),
        runtimeSessionId=runtime_session_id,
        eventType="runtime_session_created",
        message="Runtime session created.",
        metadata={"runtimeProvider": "local"},
        createdAt=datetime(2026, 6, 22, tzinfo=UTC),
    )


def runtime_session_health_response(
    runtime_session_id: uuid.UUID,
) -> MCPRuntimeSessionHealthResponse:
    return MCPRuntimeSessionHealthResponse(
        runtimeSessionId=runtime_session_id,
        runtimeProvider="local",
        runtimeKind="package",
        status="ready",
        healthy=True,
        ready=True,
        message="Runtime is ready.",
        details={"transport": "stdio"},
    )


def runtime_summary_response() -> MCPRuntimeSummaryResponse:
    return MCPRuntimeSummaryResponse(
        totalSessions=2,
        activeSessions=1,
        idleSessions=1,
        failedSessions=0,
        stoppedSessions=1,
        expiredSessions=0,
        staleActiveSessions=0,
        sessionStatusCounts={"idle": 1, "stopped": 1},
        toolCalls=MCPRuntimeToolCallSummary(
            total=4,
            succeeded=3,
            failed=1,
            running=0,
            recentTotal=2,
            recentFailed=1,
            recentFailureRate=0.5,
        ),
        recentServerErrors=[],
    )


def runtime_client(*, authenticated: bool = False) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    if authenticated:
        app.dependency_overrides[get_current_user] = fake_current_user
    return TestClient(app)


def test_list_runtime_sessions_route(monkeypatch) -> None:
    seen = {}

    async def list_runtime_sessions(session, *, workspace_id=None, status=None, limit=100):
        seen["workspace_id"] = workspace_id
        seen["status"] = status
        seen["limit"] = limit
        return MCPRuntimeSessionListResponse(
            sessions=[runtime_session_read(workspace_id=workspace_id)]
        )

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "list_runtime_sessions", list_runtime_sessions)

    response = runtime_client(authenticated=True).get(
        workspace_runtime_path("/sessions?status=idle&limit=10")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessions"][0]["serverName"] == "io.github.example/weather"
    assert "configFingerprint" not in payload["sessions"][0]
    assert "endpointUrl" not in payload["sessions"][0]
    assert seen == {"workspace_id": TEST_WORKSPACE_ID, "status": "idle", "limit": 10}


def test_get_runtime_summary_route(monkeypatch) -> None:
    seen = {}

    async def get_runtime_summary(session, *, workspace_id=None):
        seen["session"] = session
        seen["workspace_id"] = workspace_id
        return runtime_summary_response()

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "get_runtime_summary", get_runtime_summary)

    response = runtime_client(authenticated=True).get(workspace_runtime_path("/summary"))

    assert response.status_code == 200
    assert response.json()["toolCalls"]["recentFailureRate"] == 0.5
    assert seen["session"] is not None
    assert seen["workspace_id"] == TEST_WORKSPACE_ID


def test_get_runtime_session_route_returns_404(monkeypatch) -> None:
    async def get_runtime_session(session, runtime_session_id, *, workspace_id=None):
        raise MCPRuntimeSessionNotFoundError("runtime session not found")

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "get_runtime_session", get_runtime_session)

    response = runtime_client(authenticated=True).get(
        workspace_runtime_path(f"/sessions/{uuid.uuid4()}")
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "runtime session not found"
    assert response.json()["code"] == "mcp_runtime_session_not_found"
    assert response.json()["requestId"] == response.headers["x-request-id"]


def test_stop_runtime_session_route_leaves_transaction_to_dependency(monkeypatch) -> None:
    seen = {}

    async def stop_runtime_session(session, runtime_session_id, *, workspace_id=None):
        seen["session"] = session
        seen["runtime_session_id"] = runtime_session_id
        seen["workspace_id"] = workspace_id
        return runtime_session_read(workspace_id=workspace_id, status="stopped")

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_admin_or_404",
        fake_require_workspace_admin,
    )
    monkeypatch.setattr(runtime_service, "stop_runtime_session", stop_runtime_session)
    runtime_session_id = uuid.uuid4()

    response = runtime_client(authenticated=True).post(
        workspace_runtime_path(f"/sessions/{runtime_session_id}/stop")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert seen["runtime_session_id"] == runtime_session_id
    assert seen["workspace_id"] == TEST_WORKSPACE_ID
    assert seen["session"].committed is False


def test_get_runtime_session_health_route(monkeypatch) -> None:
    seen = {}
    runtime_session_id = uuid.uuid4()

    async def get_runtime_session_health(session, seen_runtime_session_id, *, workspace_id=None):
        seen["session"] = session
        seen["runtime_session_id"] = seen_runtime_session_id
        seen["workspace_id"] = workspace_id
        return runtime_session_health_response(seen_runtime_session_id)

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(
        runtime_service,
        "get_runtime_session_health",
        get_runtime_session_health,
    )

    response = runtime_client(authenticated=True).get(
        workspace_runtime_path(f"/sessions/{runtime_session_id}/health")
    )

    assert response.status_code == 200
    assert response.json()["runtimeSessionId"] == str(runtime_session_id)
    assert response.json()["status"] == "ready"
    assert response.json()["details"] == {"transport": "stdio"}
    assert seen["runtime_session_id"] == runtime_session_id
    assert seen["workspace_id"] == TEST_WORKSPACE_ID
    assert seen["session"] is not None


def test_list_runtime_session_events_route(monkeypatch) -> None:
    seen = {}
    runtime_session_id = uuid.uuid4()

    async def list_runtime_events(
        session,
        seen_runtime_session_id,
        *,
        workspace_id=None,
        limit=100,
    ):
        seen["runtime_session_id"] = seen_runtime_session_id
        seen["workspace_id"] = workspace_id
        seen["limit"] = limit
        return MCPRuntimeEventListResponse(events=[runtime_event_read(seen_runtime_session_id)])

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "list_runtime_events", list_runtime_events)

    response = runtime_client(authenticated=True).get(
        workspace_runtime_path(f"/sessions/{runtime_session_id}/events?limit=5")
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["eventType"] == "runtime_session_created"
    assert seen == {
        "runtime_session_id": runtime_session_id,
        "workspace_id": TEST_WORKSPACE_ID,
        "limit": 5,
    }


def test_workspace_list_runtime_sessions_route_filters_workspace(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    seen = {}

    async def require_workspace_member(
        session,
        current_user,
        seen_organization_id,
        seen_workspace_id,
    ):
        seen["member_check"] = (seen_organization_id, seen_workspace_id)

    async def list_runtime_sessions(session, *, workspace_id=None, status=None, limit=100):
        seen["workspace_id"] = workspace_id
        seen["status"] = status
        seen["limit"] = limit
        return MCPRuntimeSessionListResponse(
            sessions=[runtime_session_read(workspace_id=workspace_id)]
        )

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "list_runtime_sessions", list_runtime_sessions)

    response = runtime_client(authenticated=True).get(
        
            f"/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions?status=idle&limit=10"
        
    )

    assert response.status_code == 200
    assert response.json()["sessions"][0]["workspaceId"] == str(workspace_id)
    assert seen == {
        "member_check": (organization_id, workspace_id),
        "workspace_id": workspace_id,
        "status": "idle",
        "limit": 10,
    }


def test_workspace_get_runtime_summary_route_filters_workspace(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    seen = {}

    async def require_workspace_member(
        session,
        current_user,
        seen_organization_id,
        seen_workspace_id,
    ):
        seen["member_check"] = (seen_organization_id, seen_workspace_id)

    async def get_runtime_summary(session, *, workspace_id=None):
        seen["workspace_id"] = workspace_id
        return runtime_summary_response()

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "get_runtime_summary", get_runtime_summary)

    response = runtime_client(authenticated=True).get(
        f"/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
        "/mcp/runtime/summary"
    )

    assert response.status_code == 200
    assert response.json()["totalSessions"] == 2
    assert seen == {
        "member_check": (organization_id, workspace_id),
        "workspace_id": workspace_id,
    }


def test_workspace_stop_runtime_session_route_requires_admin(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()
    seen = {}

    async def require_workspace_admin(
        session,
        current_user,
        seen_organization_id,
        seen_workspace_id,
    ):
        seen["admin_check"] = (seen_organization_id, seen_workspace_id)

    async def stop_runtime_session(session, seen_runtime_session_id, *, workspace_id=None):
        seen["session"] = session
        seen["runtime_session_id"] = seen_runtime_session_id
        seen["workspace_id"] = workspace_id
        return runtime_session_read(workspace_id=workspace_id, status="stopped")

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_admin_or_404",
        require_workspace_admin,
    )
    monkeypatch.setattr(runtime_service, "stop_runtime_session", stop_runtime_session)

    response = runtime_client(authenticated=True).post(
        
            f"/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            f"/mcp/runtime/sessions/{runtime_session_id}/stop"
        
    )

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert seen["admin_check"] == (organization_id, workspace_id)
    assert seen["runtime_session_id"] == runtime_session_id
    assert seen["workspace_id"] == workspace_id
    assert seen["session"].committed is False


def test_workspace_get_runtime_session_health_route_filters_workspace(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()
    seen = {}

    async def require_workspace_member(
        session,
        current_user,
        seen_organization_id,
        seen_workspace_id,
    ):
        seen["member_check"] = (seen_organization_id, seen_workspace_id)

    async def get_runtime_session_health(session, seen_runtime_session_id, *, workspace_id=None):
        seen["runtime_session_id"] = seen_runtime_session_id
        seen["workspace_id"] = workspace_id
        return runtime_session_health_response(seen_runtime_session_id)

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        require_workspace_member,
    )
    monkeypatch.setattr(
        runtime_service,
        "get_runtime_session_health",
        get_runtime_session_health,
    )

    response = runtime_client(authenticated=True).get(
        f"/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
        f"/mcp/runtime/sessions/{runtime_session_id}/health"
    )

    assert response.status_code == 200
    assert response.json()["healthy"] is True
    assert seen == {
        "member_check": (organization_id, workspace_id),
        "runtime_session_id": runtime_session_id,
        "workspace_id": workspace_id,
    }


def test_workspace_get_runtime_session_route_returns_404_for_out_of_scope_session(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    async def require_workspace_member(*args, **kwargs):
        return None

    async def get_runtime_session(session, runtime_session_id, *, workspace_id=None):
        raise MCPRuntimeSessionNotFoundError("runtime session not found")

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "get_runtime_session", get_runtime_session)

    response = runtime_client(authenticated=True).get(
        
            f"/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            f"/mcp/runtime/sessions/{uuid.uuid4()}"
        
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "runtime session not found"
    assert response.json()["code"] == "mcp_runtime_session_not_found"
    assert response.json()["requestId"] == response.headers["x-request-id"]


def test_workspace_list_runtime_session_events_route_filters_workspace(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()
    seen = {}

    async def require_workspace_member(*args, **kwargs):
        return None

    async def list_runtime_events(
        session,
        seen_runtime_session_id,
        *,
        workspace_id=None,
        limit=100,
    ):
        seen["runtime_session_id"] = seen_runtime_session_id
        seen["workspace_id"] = workspace_id
        seen["limit"] = limit
        return MCPRuntimeEventListResponse(events=[runtime_event_read(seen_runtime_session_id)])

    monkeypatch.setattr(
        runtime_router,
        "require_workspace_member_or_404",
        require_workspace_member,
    )
    monkeypatch.setattr(runtime_service, "list_runtime_events", list_runtime_events)

    response = runtime_client(authenticated=True).get(
        f"/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
        f"/mcp/runtime/sessions/{runtime_session_id}/events?limit=5"
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["metadata"] == {"runtimeProvider": "local"}
    assert seen == {
        "runtime_session_id": runtime_session_id,
        "workspace_id": workspace_id,
        "limit": 5,
    }
