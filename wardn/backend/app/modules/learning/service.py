from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent, AgentRun, WorkspaceConversation
from app.modules.learning import repository
from app.modules.learning.models import LearningEvent
from app.modules.learning.redaction import redact_data
from app.modules.learning.schemas import EventCreate
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.scheduled_tasks.models import WorkspaceScheduledTask, WorkspaceScheduledTaskRun


async def validate_provenance(session: AsyncSession, event: EventCreate) -> None:
    await repository.require_workspace(session, event.organization_id, event.workspace_id)
    model = {
        "agent_run": AgentRun,
        "scheduled_run": WorkspaceScheduledTaskRun,
        "tool_invocation": MCPToolInvocation,
    }[event.execution_kind]
    execution = await session.scalar(
        select(model).where(
            model.id == event.execution_id,
            model.organization_id == event.organization_id,
            model.workspace_id == event.workspace_id,
        )
    )
    if execution is None:
        raise ValueError("learning execution not found in workspace")
    for field, reference_model in (
        ("agent_id", Agent),
        ("conversation_id", WorkspaceConversation),
        ("scheduled_run_id", WorkspaceScheduledTaskRun),
        ("scheduled_task_id", WorkspaceScheduledTask),
        ("tool_call_id", MCPToolInvocation),
    ):
        value = getattr(event, field)
        if value is None:
            continue
        reference = await session.scalar(
            select(reference_model).where(
                reference_model.id == value,
                reference_model.organization_id == event.organization_id,
            )
        )
        if reference is None or (
            reference.workspace_id != event.workspace_id
            and not (reference_model is Agent and reference.workspace_id is None)
        ):
            raise ValueError(f"learning {field} not found in workspace")
        if field in {"agent_id", "conversation_id"}:
            actual = getattr(execution, field, None)
            if actual is not None and actual != value:
                raise ValueError(f"learning {field} does not belong to execution")
        if field == "tool_call_id":
            expected = reference.agent_run_id or reference.id
            if expected != event.execution_id:
                raise ValueError("learning tool call does not belong to execution")
        if field == "scheduled_run_id":
            if event.scheduled_task_id != reference.task_id:
                raise ValueError("learning scheduled task/run mismatch")
            if event.execution_kind == "scheduled_run" and value != event.execution_id:
                raise ValueError("learning scheduled execution mismatch")
            # During agent creation the schedule row has not yet been linked back to it.
            if event.execution_kind == "agent_run" and reference.agent_id != execution.agent_id:
                raise ValueError("learning scheduled agent mismatch")
    if event.parent_event_id is not None:
        parent = await session.scalar(
            select(LearningEvent.id).where(
                LearningEvent.id == event.parent_event_id,
                LearningEvent.organization_id == event.organization_id,
                LearningEvent.workspace_id == event.workspace_id,
                LearningEvent.execution_id == event.execution_id,
            )
        )
        if parent is None:
            raise ValueError("learning parent event not found in execution")


class LearningEventEmitter:
    """Append only, with no provider calls, background tasks or independent commits."""

    async def emit(self, session: AsyncSession, event: EventCreate) -> LearningEvent:
        await validate_provenance(session, event)
        safe_event = event.model_copy(
            update={
                "data": redact_data(event.data, event.sensitive_paths),
            }
        )
        return await repository.append_event(session, safe_event)


emitter = LearningEventEmitter()
