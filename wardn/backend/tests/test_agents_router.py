import uuid
from types import SimpleNamespace

import pytest

from app.modules.agents import router as agents_router
from app.modules.agents.schemas import (
    AgentToolApprovalDecisionRequest,
    AgentToolApprovalDecisionResponse,
)
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_tool_approval_route_uses_durable_resume_scheduler(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), email="owner@example.com", is_active=True)
    session = SimpleNamespace(info={})
    durable_scheduler = object()

    async def decide_agent_tool_approval(
        session_arg,
        user_arg,
        organization_id_arg,
        workspace_id_arg,
        agent_id_arg,
        approval_id_arg,
        payload_arg,
        *,
        schedule_completion,
    ):
        assert session_arg is session
        assert user_arg is user
        assert organization_id_arg == organization_id
        assert workspace_id_arg == workspace_id
        assert agent_id_arg == agent_id
        assert approval_id_arg == approval_id
        assert payload_arg.decision == "approve"
        assert schedule_completion is durable_scheduler
        return AgentToolApprovalDecisionResponse(
            approval_id=approval_id,
            status="running",
            tool_name="jira_get_issue",
        )

    monkeypatch.setattr(
        agents_router,
        "decide_agent_tool_approval",
        decide_agent_tool_approval,
    )
    monkeypatch.setattr(
        agents_router,
        "enqueue_agent_tool_approval_resume",
        durable_scheduler,
    )

    response = await agents_router.decide_workspace_agent_tool_approval_route(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
        payload=AgentToolApprovalDecisionRequest(decision="approve"),
        session=session,
        current_user=user,
    )

    assert response.status == "running"
