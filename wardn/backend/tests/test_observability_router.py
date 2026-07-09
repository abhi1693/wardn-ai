import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.observability import router as observability_router
from app.modules.observability import service as observability_service
from app.modules.observability.schemas import (
    MCPToolUsageListResponse,
    MCPToolUsageRead,
    MCPToolUsageSummary,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

TEST_ORGANIZATION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEST_WORKSPACE_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


class FakeSession:
    pass


async def fake_session():
    yield FakeSession()


async def fake_current_user():
    return User(id=uuid.uuid4(), email="admin@example.com", is_superuser=True)


async def fake_require_workspace_member(*args, **kwargs):
    return None


def observability_client(*, authenticated: bool = False) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    if authenticated:
        app.dependency_overrides[get_current_user] = fake_current_user
    return TestClient(app)


def workspace_observability_path(suffix: str = "") -> str:
    return (
        f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/workspaces/{TEST_WORKSPACE_ID}"
        f"/observability{suffix}"
    )


def tool_usage_response() -> MCPToolUsageListResponse:
    return MCPToolUsageListResponse(
        summary=MCPToolUsageSummary(
            total=1,
            succeeded=1,
            failed=0,
            running=0,
            attributed=1,
            unattributed=0,
            averageDurationMs=123,
        ),
        toolCalls=[
            MCPToolUsageRead(
                id=uuid.uuid4(),
                organizationId=TEST_ORGANIZATION_ID,
                workspaceId=TEST_WORKSPACE_ID,
                runtimeSessionId=uuid.uuid4(),
                installationId=uuid.uuid4(),
                userId=uuid.uuid4(),
                userEmail="user@example.com",
                userDisplayName="Test User",
                agentId=uuid.uuid4(),
                agentName="Workspace Assistant",
                agentRunId=uuid.uuid4(),
                serverName="io.github.example/weather",
                serverVersion="1.0.0",
                toolName="get_forecast",
                status="succeeded",
                startedAt=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
                finishedAt=datetime(2026, 7, 9, 12, 0, 1, tzinfo=UTC),
                durationMs=123,
                inputSizeBytes=42,
                outputSizeBytes=84,
                isError=False,
                error="",
            )
        ],
    )


def test_list_mcp_tool_usage_route(monkeypatch) -> None:
    seen = {}

    async def list_workspace_mcp_tool_usage(
        session,
        *,
        organization_id,
        workspace_id,
        limit=100,
    ):
        seen["organization_id"] = organization_id
        seen["workspace_id"] = workspace_id
        seen["limit"] = limit
        return tool_usage_response()

    monkeypatch.setattr(
        observability_router,
        "require_workspace_member",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(
        observability_service,
        "list_workspace_mcp_tool_usage",
        list_workspace_mcp_tool_usage,
    )

    response = observability_client(authenticated=True).get(
        workspace_observability_path("/mcp-tool-usage?limit=25")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["averageDurationMs"] == 123
    assert payload["toolCalls"][0]["userDisplayName"] == "Test User"
    assert payload["toolCalls"][0]["agentName"] == "Workspace Assistant"
    assert seen == {
        "organization_id": TEST_ORGANIZATION_ID,
        "workspace_id": TEST_WORKSPACE_ID,
        "limit": 25,
    }
