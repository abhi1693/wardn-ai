import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.db.session import DEFERRED_SESSION_WORK_KEY
from app.modules.agents import router as agents_router
from app.modules.agents.schemas import (
    AgentToolApprovalDecisionRequest,
    AgentToolApprovalDecisionResponse,
)
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_tool_approval_route_defers_completion_until_after_commit(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), email="owner@example.com", is_active=True)
    session = SimpleNamespace(info={})
    completion_started = asyncio.Event()
    completion_args: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]] = []

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
        schedule_completion(approval_id)
        return AgentToolApprovalDecisionResponse(
            approval_id=approval_id,
            status="running",
            tool_name="jira_get_issue",
        )

    async def complete_agent_tool_approval_background(
        organization_id_arg,
        workspace_id_arg,
        agent_id_arg,
        approval_id_arg,
        user_id_arg,
    ):
        completion_args.append(
            (
                organization_id_arg,
                workspace_id_arg,
                agent_id_arg,
                approval_id_arg,
                user_id_arg,
            )
        )
        completion_started.set()

    monkeypatch.setattr(
        agents_router,
        "decide_agent_tool_approval",
        decide_agent_tool_approval,
    )
    monkeypatch.setattr(
        agents_router,
        "complete_agent_tool_approval_background",
        complete_agent_tool_approval_background,
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
    assert not completion_started.is_set()

    work_items = session.info[DEFERRED_SESSION_WORK_KEY]
    assert len(work_items) == 1

    await work_items[0](session)
    await asyncio.wait_for(completion_started.wait(), timeout=1)
    assert completion_args == [
        (organization_id, workspace_id, agent_id, approval_id, user.id),
    ]
