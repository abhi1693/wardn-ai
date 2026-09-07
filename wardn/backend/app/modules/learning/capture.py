"""Adapters for existing durable actions; never inspect provider reasoning or tool payloads."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.agents.models import AgentRun, AgentRunStep, AgentToolApproval, ConversationMessage
from app.modules.learning.models import LearningEvent
from app.modules.learning.schemas import EventCreate, EventType
from app.modules.learning.service import emitter
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.scheduled_tasks.models import WorkspaceScheduledTaskRun

STATUS_EVENTS = {
    "running": EventType.EXECUTION_RESUMED,
    "waiting_confirmation": EventType.EXECUTION_PAUSED,
    "queued": EventType.EXECUTION_PAUSED,
    "succeeded": EventType.EXECUTION_SUCCEEDED,
    "partially_delivered": EventType.EXECUTION_SUCCEEDED,
    "delivery_failed": EventType.EXECUTION_FAILED,
    "failed": EventType.EXECUTION_FAILED,
    "canceled": EventType.EXECUTION_CANCELLED,
}


def enabled(session: AsyncSession) -> bool:
    # Other domains use lightweight non-database doubles in unit tests.
    return isinstance(session, AsyncSession) and get_settings().learning_events_enabled


async def run_context(session: AsyncSession, run: AgentRun) -> dict:
    first = await session.scalar(
        select(LearningEvent)
        .where(
            LearningEvent.organization_id == run.organization_id,
            LearningEvent.workspace_id == run.workspace_id,
            LearningEvent.execution_id == run.id,
            LearningEvent.event_type == EventType.EXECUTION_STARTED,
        )
        .order_by(LearningEvent.sequence_number)
        .limit(1)
    )
    return {
        "organization_id": run.organization_id,
        "workspace_id": run.workspace_id,
        "execution_id": run.id,
        "execution_kind": "agent_run",
        "source": "agents",
        "agent_id": run.agent_id,
        "conversation_id": run.conversation_id,
        "scheduled_run_id": first.scheduled_run_id if first else None,
        "scheduled_task_id": first.scheduled_task_id if first else None,
    }


async def agent_run_started(
    session: AsyncSession,
    run: AgentRun,
    *,
    scheduled_run_id: uuid.UUID | None = None,
) -> None:
    if not enabled(session):
        return
    context = await run_context(session, run)
    if scheduled_run_id is not None:
        scheduled = await session.scalar(
            select(WorkspaceScheduledTaskRun).where(
                WorkspaceScheduledTaskRun.id == scheduled_run_id,
                WorkspaceScheduledTaskRun.organization_id == run.organization_id,
                WorkspaceScheduledTaskRun.workspace_id == run.workspace_id,
            )
        )
        if scheduled is None:
            raise ValueError("learning scheduled run not found")
        context.update(scheduled_run_id=scheduled.id, scheduled_task_id=scheduled.task_id)
    await emitter.emit(
        session,
        EventCreate(
            **context,
            event_type=EventType.EXECUTION_STARTED,
            idempotency_key=f"agent:{run.id}:started",
            occurred_at=run.started_at,
            data={
                "trigger_type": run.trigger_type,
                "source_ref": f"agent_runs:{run.id}",
                "previous_execution_id": str(run.previous_agent_run_id)
                if run.previous_agent_run_id
                else None,
            },
        ),
    )


async def agent_run_status(session: AsyncSession, run: AgentRun) -> None:
    if not enabled(session) or run.status not in STATUS_EVENTS:
        return
    # A resumed execution can pause repeatedly. Persisted transition timestamp identifies it.
    at = run.updated_at or datetime.now(UTC)
    await emitter.emit(
        session,
        EventCreate(
            **await run_context(session, run),
            event_type=STATUS_EVENTS[run.status],
            idempotency_key=f"agent:{run.id}:{run.status}:{at.isoformat()}",
            occurred_at=at,
            data={
                "status": run.status,
                "error_present": bool(run.error),
                "source_ref": f"agent_runs:{run.id}",
            },
        ),
    )


async def conversation_message(session: AsyncSession, message: ConversationMessage) -> None:
    if (
        not enabled(session)
        or message.agent_run_id is None
        or message.role not in {"user", "assistant"}
    ):
        return
    run = await session.get(AgentRun, message.agent_run_id)
    if run is None or run.conversation_id != message.conversation_id:
        raise ValueError("learning conversation message/run mismatch")
    await emitter.emit(
        session,
        EventCreate(
            **await run_context(session, run),
            event_type=EventType.USER_MESSAGE
            if message.role == "user"
            else EventType.AGENT_RESPONSE,
            idempotency_key=f"message:{message.id}",
            occurred_at=message.created_at,
            data={
                "source_ref": f"conversation_messages:{message.id}",
                "content_chars": len(message.content),
                "message_sequence": message.sequence,
            },
        ),
    )


async def agent_step(session: AsyncSession, run: AgentRun | None, step: AgentRunStep) -> None:
    if not enabled(session) or run is None:
        return
    event_type = None
    data = {"source_ref": f"agent_run_steps:{step.id}", "status": step.status}
    if run.conversation_id is None:
        event_type = {
            "model_input": EventType.USER_MESSAGE,
            "model_output": EventType.AGENT_RESPONSE,
        }.get(step.step_type)
    if step.step_type == "tool_approval":
        event_type = {
            "running": EventType.APPROVAL_GRANTED,
            "denied": EventType.APPROVAL_REJECTED,
            "expired": EventType.APPROVAL_EXPIRED,
        }.get(step.status)
        data["approval_id"] = step.payload.get("approvalId")
    if step.step_type == "guardrail_decision":
        event_type = EventType.AGENT_DECISION
        data["decision_kind"] = "guardrail_evaluation"
        data["policy_id"] = step.payload.get("policyId")
    if step.step_type == "tool_result" and step.status == "completed":
        details = step.payload.get("details")
        snapshot = details.get("externalSkillSnapshot") if isinstance(details, dict) else None
        if isinstance(snapshot, dict) and snapshot.get("id") and snapshot.get("content_hash"):
            event_type = EventType.SKILL_EXTERNAL_RETRIEVED
            data["external_skill"] = {
                "id": snapshot["id"],
                "content_hash": snapshot["content_hash"],
            }
    if event_type is not None:
        await emitter.emit(
            session,
            EventCreate(
                **await run_context(session, run),
                event_type=event_type,
                idempotency_key=f"step:{step.id}",
                occurred_at=step.created_at,
                data=data,
            ),
        )


async def approval_requested(session: AsyncSession, approval: AgentToolApproval) -> None:
    if not enabled(session) or approval.agent_run_id is None:
        return
    run = await session.get(AgentRun, approval.agent_run_id)
    if run is None:
        raise ValueError("learning approval run not found")
    await emitter.emit(
        session,
        EventCreate(
            **await run_context(session, run),
            event_type=EventType.APPROVAL_REQUESTED,
            idempotency_key=f"approval:{approval.id}:requested",
            occurred_at=approval.created_at,
            data={
                "source_ref": f"agent_tool_approvals:{approval.id}",
                "provider_tool_call_id": approval.tool_call_id,
                "tool": approval.tool_name,
            },
        ),
    )


async def tool_event(
    session: AsyncSession,
    invocation: MCPToolInvocation,
    event_type: EventType,
) -> LearningEvent | None:
    if (
        not enabled(session)
        or invocation.workspace_id is None
        or invocation.organization_id is None
    ):
        return None
    context = {
        "organization_id": invocation.organization_id,
        "workspace_id": invocation.workspace_id,
        "execution_id": invocation.id,
        "execution_kind": "tool_invocation",
        "agent_id": invocation.agent_id,
    }
    if invocation.agent_run_id is not None:
        run = await session.get(AgentRun, invocation.agent_run_id)
        if run is None:
            raise ValueError("learning invocation run not found")
        context = await run_context(session, run)
    context["source"] = "mcp_runtime"
    return await emitter.emit(
        session,
        EventCreate(
            **context,
            event_type=event_type,
            tool_call_id=invocation.id,
            idempotency_key=f"tool:{invocation.id}:{event_type}",
            occurred_at=invocation.finished_at or invocation.started_at,
            data={
                "source_ref": f"mcp_tool_invocations:{invocation.id}",
                "server": invocation.server_name,
                "server_version": invocation.server_version,
                "tool": invocation.tool_name,
                "installation_id": str(invocation.installation_id),
                "duration_ms": invocation.duration_ms,
                "input_size_bytes": invocation.input_size_bytes,
                "output_size_bytes": invocation.output_size_bytes,
                "success": invocation.status == "succeeded" and not invocation.is_error,
                "error_present": bool(invocation.error),
            },
        ),
    )


async def tool_started(session: AsyncSession, invocation: MCPToolInvocation) -> None:
    if not enabled(session):
        return
    if invocation.agent_run_id is None:
        await tool_event(session, invocation, EventType.EXECUTION_STARTED)
    await tool_event(session, invocation, EventType.TOOL_SELECTED)
    await tool_event(session, invocation, EventType.TOOL_CALL_STARTED)
    session.info["learning_invocation_id"] = invocation.id


async def tool_finished(session: AsyncSession, invocation: MCPToolInvocation) -> None:
    if not enabled(session):
        return
    failed = invocation.status != "succeeded" or invocation.is_error
    await tool_event(
        session, invocation, EventType.TOOL_CALL_FAILED if failed else EventType.TOOL_CALL_COMPLETED
    )
    if invocation.agent_run_id is None:
        await tool_event(
            session,
            invocation,
            EventType.EXECUTION_FAILED if failed else EventType.EXECUTION_SUCCEEDED,
        )


async def tool_observed(session: AsyncSession, *, invocation_id: uuid.UUID | None = None) -> None:
    if not enabled(session):
        return
    invocation_id = invocation_id or session.info.pop("learning_invocation_id", None)
    if invocation_id is not None:
        invocation = await session.get(MCPToolInvocation, invocation_id)
        if invocation is not None:
            # Observable handoff to the orchestrator, not a claim about model cognition.
            await tool_event(session, invocation, EventType.TOOL_RESULT_OBSERVED)


async def scheduled_status(
    session: AsyncSession,
    run: WorkspaceScheduledTaskRun,
    *,
    now: datetime | None = None,
) -> None:
    if not enabled(session) or run.status not in STATUS_EVENTS:
        return
    event_type = STATUS_EVENTS[run.status]
    if run.status == "running" and run.attempt_count == 1:
        event_type = EventType.EXECUTION_STARTED
    await emitter.emit(
        session,
        EventCreate(
            organization_id=run.organization_id,
            workspace_id=run.workspace_id,
            execution_id=run.id,
            execution_kind="scheduled_run",
            source="scheduled_tasks",
            agent_id=run.agent_id,
            conversation_id=run.conversation_id,
            scheduled_task_id=run.task_id,
            scheduled_run_id=run.id,
            event_type=event_type,
            idempotency_key=f"scheduled:{run.id}:{run.attempt_count}:{run.status}",
            occurred_at=now or run.finished_at or datetime.now(UTC),
            data={
                "source_ref": f"workspace_scheduled_task_runs:{run.id}",
                "status": run.status,
                "attempt": run.attempt_count,
                "agent_execution_id": str(run.agent_run_id) if run.agent_run_id else None,
                "trigger_source": run.trigger_source,
                "error_present": bool(run.error),
            },
        ),
    )
