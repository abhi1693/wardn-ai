import uuid
from datetime import UTC, datetime

import pytest

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability import service
from app.modules.users.models import User


def tool_invocation(
    *,
    status: str = "succeeded",
    is_error: bool = False,
    user_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    duration_ms: int | None = 120,
) -> MCPToolInvocation:
    return MCPToolInvocation(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        runtime_session_id=uuid.uuid4(),
        user_id=user_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        tool_name="get_forecast",
        status=status,
        started_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 9, 12, 0, 1, tzinfo=UTC),
        duration_ms=duration_ms,
        input_size_bytes=42,
        output_size_bytes=84,
        is_error=is_error,
        error="",
    )


def test_tool_usage_read_includes_person_and_agent_labels() -> None:
    user_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    invocation = tool_invocation(user_id=user_id, agent_id=agent_id)
    user = User(
        id=user_id,
        email="user@example.com",
        first_name="Asha",
        last_name="Rao",
    )
    agent = Agent(
        id=agent_id,
        organization_id=invocation.organization_id,
        workspace_id=invocation.workspace_id,
        name="Workspace Assistant",
        instructions="Use tools.",
        scope="workspace",
        model_name="gpt-4o-mini",
    )

    response = service.tool_usage_read(invocation, user, agent)

    assert response.user_display_name == "Asha Rao"
    assert response.user_email == "user@example.com"
    assert response.agent_name == "Workspace Assistant"
    assert response.input_size_bytes == 42
    assert response.output_size_bytes == 84


def test_tool_usage_summary_counts_status_and_attribution() -> None:
    attributed = tool_invocation(
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
        duration_ms=100,
    )
    failed = tool_invocation(status="failed", is_error=True, duration_ms=300)
    running = tool_invocation(status="running", duration_ms=None)

    summary = service.tool_usage_summary([attributed, failed, running])

    assert summary.total == 3
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.running == 1
    assert summary.attributed == 1
    assert summary.unattributed == 2
    assert summary.average_duration_ms == 200


@pytest.mark.asyncio
async def test_list_workspace_mcp_tool_usage_uses_repository(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    invocation = tool_invocation(user_id=user_id)
    user = User(id=user_id, email="user@example.com")

    async def list_mcp_tool_usage(session, *, organization_id, workspace_id, limit):
        return [(invocation, user, None)]

    monkeypatch.setattr(service.repository, "list_mcp_tool_usage", list_mcp_tool_usage)

    response = await service.list_workspace_mcp_tool_usage(
        object(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=25,
    )

    assert response.summary.total == 1
    assert response.tool_calls[0].user_email == "user@example.com"
