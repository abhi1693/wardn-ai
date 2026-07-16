import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository
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
)
from app.modules.agents.tool_execution import mcp_result_text
from app.modules.agents.types import AgentChatTextEvent
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.mcp_runtime.service import call_tool_with_tracking
from app.modules.organizations.service import require_workspace_member
from app.modules.users.models import User


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


async def decide_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: AgentToolApprovalDecisionRequest,
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
    if approval.status != "pending":
        return AgentToolApprovalDecisionResponse(
            approval_id=approval.id,
            status=approval.status,
            tool_name=approval.tool_name,
            result=approval.result,
            error=approval.error,
            assistant_message=None,
        )

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
        return AgentToolApprovalDecisionResponse(
            approval_id=approval.id,
            status=approval.status,
            tool_name=approval.tool_name,
            result=approval.result,
            error=approval.error,
            assistant_message=None,
        )

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
            result = await call_tool_with_tracking(
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
    return AgentToolApprovalDecisionResponse(
        approval_id=approval.id,
        status=approval.status,
        tool_name=approval.tool_name,
        result=approval.result,
        error=approval.error,
        assistant_message=conversation_message_response(assistant_message)
        if assistant_message is not None
        else None,
    )
