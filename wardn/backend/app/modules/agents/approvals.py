import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.modules.agents import repository
from app.modules.agents.approval_expiry import (
    agent_tool_approval_expires_at,
    agent_tool_approval_is_expired,
)
from app.modules.agents.approval_links import agent_tool_approval_url
from app.modules.agents.chat_orchestrator import chat_stream_error_text, run_agent_chat
from app.modules.agents.exceptions import AgentNotFoundError, InvalidAgentScopeError
from app.modules.agents.mappers import (
    conversation_message_response,
    sanitize_run_payload,
    text_parts,
)
from app.modules.agents.models import Agent, AgentToolApproval, ConversationMessage
from app.modules.agents.provider_clients import agent_runtime_tools, validate_provider_credential
from app.modules.agents.schemas import (
    AgentChatMessage,
    AgentChatRequest,
    AgentToolApprovalDecisionRequest,
    AgentToolApprovalDecisionResponse,
    AgentToolApprovalRead,
)
from app.modules.agents.tool_execution import action_review_payload, mcp_result_text
from app.modules.agents.types import AgentChatTextEvent
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.mcp_runtime.service import call_tool_with_isolated_tracking
from app.modules.organizations.service import require_workspace_member
from app.modules.users import repository as users_repository
from app.modules.users.models import User

logger = logging.getLogger(__name__)
AgentToolApprovalScheduler = Callable[[uuid.UUID], None]
APPROVAL_EXPIRED_ERROR = "Tool approval expired before it was approved."


def conversation_message_to_chat_message(message: ConversationMessage) -> AgentChatMessage:
    return AgentChatMessage(
        role=message.role,
        parts=message.parts or text_parts(message.content),
    )


def approval_continuation_prompt(approval: AgentToolApproval) -> str:
    result = approval.result.strip() or "(no tool output)"
    return (
        "The user approved the pending MCP tool call. Continue the assistant response using "
        "the approved tool result. Do not ask for approval again for this completed call.\n\n"
        f"Tool: {approval.tool_name}\n"
        f"Result:\n{result}"
    )


def agent_tool_approval_read(
    approval: AgentToolApproval,
    *,
    action_review: dict[str, Any] | None = None,
) -> AgentToolApprovalRead:
    return AgentToolApprovalRead(
        id=approval.id,
        organization_id=approval.organization_id,
        workspace_id=approval.workspace_id,
        agent_id=approval.agent_id,
        conversation_id=approval.conversation_id,
        agent_run_id=approval.agent_run_id,
        requested_by_id=approval.requested_by_id,
        decided_by_id=approval.decided_by_id,
        installation_id=approval.installation_id,
        tool_schema_id=approval.tool_schema_id,
        tool_call_id=approval.tool_call_id,
        tool_name=approval.tool_name,
        arguments=approval.arguments,
        status=approval.status,
        result=approval.result,
        error=approval.error,
        expires_at=agent_tool_approval_expires_at(approval),
        approval_url=agent_tool_approval_url(
            organization_id=approval.organization_id,
            workspace_id=approval.workspace_id,
            agent_id=approval.agent_id,
            approval_id=approval.id,
        ),
        action_review=action_review,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


async def approval_action_review(
    session: AsyncSession,
    approval: AgentToolApproval,
    *,
    agent: Agent,
) -> dict[str, Any] | None:
    runtime_rows = await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    runtime_tools = agent_runtime_tools(runtime_rows)
    tool = next(
        (
            candidate
            for candidate in runtime_tools.values()
            if candidate.installation.id == approval.installation_id
            and candidate.tool_schema.id == approval.tool_schema_id
        ),
        None,
    )
    if tool is None:
        return None
    return action_review_payload(
        approval=approval,
        tool=tool,
        decision_details={},
    )


async def get_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
) -> AgentToolApprovalRead:
    await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    approval = await repository.get_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise AgentNotFoundError("tool approval not found")
    if approval.requested_by_id and approval.requested_by_id != user.id and not user.is_superuser:
        raise InvalidAgentScopeError("tool approval belongs to another user")
    return agent_tool_approval_read(
        approval,
        action_review=await approval_action_review(session, approval, agent=agent),
    )


async def generate_approval_continuation_message(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent: Agent,
    approval: AgentToolApproval,
) -> ConversationMessage | None:
    if approval.conversation_id is None or approval.status != "completed":
        return None
    if agent.provider_credential_id is None or not agent.model_name:
        return None
    credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=agent.workspace_id,
        provider_credential_id=agent.provider_credential_id,
    )
    if credential is None:
        return None
    messages = await repository.list_conversation_messages(
        session,
        conversation_id=approval.conversation_id,
    )
    chat_messages = [conversation_message_to_chat_message(message) for message in messages]
    chat_messages.append(
        AgentChatMessage(role="user", parts=text_parts(approval_continuation_prompt(approval)))
    )
    stream = run_agent_chat(
        agent,
        credential,
        AgentChatRequest(id=str(approval.conversation_id), messages=chat_messages),
        {},
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation=None,
        agent_run=None,
    )
    chunks: list[str] = []
    try:
        async for event in stream:
            if isinstance(event, AgentChatTextEvent) and event.text:
                chunks.append(event.text)
    except Exception as exc:
        chunks.append(chat_stream_error_text(exc))
    content = "".join(chunks).strip()
    if not content:
        return None
    message = await repository.append_conversation_message(
        session,
        conversation_id=approval.conversation_id,
        role="assistant",
        content=content,
        parts=text_parts(content),
        agent_run_id=approval.agent_run_id,
    )
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="model_output",
            status="succeeded",
            title="Assistant response",
            payload={"content": sanitize_run_payload(content)},
        )
    return message


def agent_tool_approval_decision_response(
    approval: AgentToolApproval,
    *,
    assistant_message: ConversationMessage | None = None,
) -> AgentToolApprovalDecisionResponse:
    return AgentToolApprovalDecisionResponse(
        approval_id=approval.id,
        status=approval.status,
        tool_name=approval.tool_name,
        result=approval.result,
        error=approval.error,
        expires_at=agent_tool_approval_expires_at(approval),
        assistant_message=conversation_message_response(assistant_message)
        if assistant_message is not None
        else None,
    )


async def set_agent_tool_approval_running(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    approval: AgentToolApproval,
) -> None:
    approval.status = "running"
    approval.error = ""
    await session.flush()
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="tool_approval",
            status="running",
            title=approval.tool_name,
            payload={"approvalId": str(approval.id), "decision": "approve"},
        )
        agent_run = await repository.get_agent_run(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_run_id=approval.agent_run_id,
        )
        if agent_run is not None:
            await repository.mark_agent_run_running(session, agent_run)
    if approval.conversation_id is not None:
        await repository.update_conversation_tool_activity(
            session,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            data_update={"status": "running"},
        )


async def expire_agent_tool_approval(
    session: AsyncSession,
    approval: AgentToolApproval,
    *,
    error: str = APPROVAL_EXPIRED_ERROR,
) -> None:
    approval.status = "expired"
    approval.error = error
    await session.flush()
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="tool_approval",
            status="expired",
            title=approval.tool_name,
            payload={"approvalId": str(approval.id), "error": error},
        )
    if approval.conversation_id is not None:
        await repository.update_conversation_tool_activity(
            session,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            data_update={"status": "expired", "error": error},
        )
    if approval.agent_run_id is not None:
        agent_run = await repository.get_agent_run(
            session,
            organization_id=approval.organization_id,
            workspace_id=approval.workspace_id,
            agent_run_id=approval.agent_run_id,
        )
        if agent_run is not None:
            await repository.finish_agent_run(
                session,
                agent_run,
                status="failed",
                error=error,
            )


async def complete_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
) -> AgentToolApprovalDecisionResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    approval = await repository.get_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise AgentNotFoundError("tool approval not found")
    if approval.requested_by_id and approval.requested_by_id != user.id and not user.is_superuser:
        raise InvalidAgentScopeError("tool approval belongs to another user")
    if approval.status == "pending" and agent_tool_approval_is_expired(approval):
        await expire_agent_tool_approval(session, approval)
        return agent_tool_approval_decision_response(approval)
    if approval.status == "pending":
        await set_agent_tool_approval_running(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            approval=approval,
        )
    elif approval.status != "running":
        return agent_tool_approval_decision_response(approval)

    runtime_rows = await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    runtime_tools = agent_runtime_tools(runtime_rows)
    tool = next(
        (
            candidate
            for candidate in runtime_tools.values()
            if candidate.installation.id == approval.installation_id
            and candidate.tool_schema.id == approval.tool_schema_id
        ),
        None,
    )
    if tool is None:
        approval.status = "failed"
        approval.error = "Tool is no longer assigned to this agent."
    else:
        try:
            result = await call_tool_with_isolated_tracking(
                session,
                tool.installation,
                tool.server,
                tool_name=tool.tool_schema.tool_name,
                arguments=approval.arguments,
                user_id=user.id,
                agent_id=agent.id,
                agent_run_id=approval.agent_run_id,
            )
            approval.status = "completed"
            approval.result = mcp_result_text(result)
            approval.error = ""
        except (MCPGatewayUpstreamError, KubernetesRuntimeProviderError) as exc:
            approval.status = "failed"
            approval.error = str(exc)
        except Exception as exc:
            logger.exception(
                "Agent tool approval execution failed.",
                extra={
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id),
                    "agent_id": str(agent_id),
                    "approval_id": str(approval_id),
                },
            )
            approval.status = "failed"
            approval.error = str(exc)
    await session.flush()
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="tool_approval",
            status=approval.status,
            title=approval.tool_name,
            payload=sanitize_run_payload(
                {
                    "approvalId": str(approval.id),
                    "decision": "approve",
                    "result": approval.result,
                    "error": approval.error,
                }
            ),
        )
    if approval.conversation_id is not None:
        update: dict[str, Any] = {"status": approval.status}
        if approval.result:
            update["result"] = sanitize_run_payload(approval.result)
        if approval.error:
            update["error"] = approval.error
        await repository.update_conversation_tool_activity(
            session,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            data_update=update,
        )
    assistant_message = None
    if approval.status == "completed":
        assistant_message = await generate_approval_continuation_message(
            session,
            user,
            organization_id,
            workspace_id,
            agent,
            approval,
        )
    if approval.agent_run_id is not None:
        agent_run = await repository.get_agent_run(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_run_id=approval.agent_run_id,
        )
        if agent_run is not None:
            await repository.finish_agent_run(
                session,
                agent_run,
                status="succeeded" if approval.status == "completed" else "failed",
                error=approval.error,
            )
    return agent_tool_approval_decision_response(
        approval,
        assistant_message=assistant_message,
    )


async def complete_agent_tool_approval_background(
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            user = await users_repository.get_user_by_id(session, user_id)
            if user is None or not user.is_active:
                logger.warning(
                    "Skipping agent tool approval completion because user is inactive.",
                    extra={
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id),
                        "agent_id": str(agent_id),
                        "approval_id": str(approval_id),
                        "user_id": str(user_id),
                    },
                )
                return
            await complete_agent_tool_approval(
                session,
                user,
                organization_id,
                workspace_id,
                agent_id,
                approval_id,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "Background agent tool approval completion failed.",
                extra={
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id),
                    "agent_id": str(agent_id),
                    "approval_id": str(approval_id),
                    "user_id": str(user_id),
                },
            )


async def decide_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: AgentToolApprovalDecisionRequest,
    *,
    schedule_completion: AgentToolApprovalScheduler | None = None,
) -> AgentToolApprovalDecisionResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    approval = await repository.get_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise AgentNotFoundError("tool approval not found")
    if approval.requested_by_id and approval.requested_by_id != user.id and not user.is_superuser:
        raise InvalidAgentScopeError("tool approval belongs to another user")
    if approval.status == "pending" and agent_tool_approval_is_expired(approval):
        await expire_agent_tool_approval(session, approval)
        return agent_tool_approval_decision_response(approval)
    if approval.status != "pending":
        return agent_tool_approval_decision_response(approval)

    approval.decided_by_id = user.id
    if payload.decision == "deny":
        approval.status = "denied"
        approval.error = "Denied by user."
        await session.flush()
        if approval.agent_run_id is not None:
            await repository.append_agent_run_step(
                session,
                agent_run_id=approval.agent_run_id,
                step_type="tool_approval",
                status="denied",
                title=approval.tool_name,
                payload={"approvalId": str(approval.id), "decision": "deny"},
            )
        if approval.conversation_id is not None:
            await repository.update_conversation_tool_activity(
                session,
                conversation_id=approval.conversation_id,
                approval_id=approval.id,
                data_update={"status": "denied", "error": approval.error},
            )
        if approval.agent_run_id is not None:
            agent_run = await repository.get_agent_run(
                session,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_run_id=approval.agent_run_id,
            )
            if agent_run is not None:
                await repository.finish_agent_run(
                    session,
                    agent_run,
                    status="denied",
                    error=approval.error,
                )
        return agent_tool_approval_decision_response(approval)

    await set_agent_tool_approval_running(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        approval=approval,
    )
    if schedule_completion is not None:
        schedule_completion(approval.id)
        return agent_tool_approval_decision_response(approval)
    return await complete_agent_tool_approval(
        session,
        user,
        organization_id,
        workspace_id,
        agent_id,
        approval.id,
    )
