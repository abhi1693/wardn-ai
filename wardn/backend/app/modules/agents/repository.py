import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.modules.agents.models import (
    Agent,
    AgentApprovedSkillAssignment,
    AgentMCPServerAssignment,
    AgentMCPToolAssignment,
    AgentRun,
    AgentRunResumeJob,
    AgentRunStep,
    AgentToolApproval,
    ConversationMessage,
    WorkspaceApprovedSkill,
    WorkspaceConversation,
)
from app.modules.chat_providers.models import ChatProviderConnection, ChatProviderThread
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.organizations.models import (
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)

ADMIN_ROLES = ("owner", "admin")


async def get_agent(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    include_inactive: bool = False,
) -> Agent | None:
    statement = select(Agent).where(
        Agent.id == agent_id,
        Agent.organization_id == organization_id,
    )
    if workspace_id is not None:
        statement = statement.where(Agent.workspace_id == workspace_id)
    if not include_inactive:
        statement = statement.where(Agent.is_active.is_(True))
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_agent_by_name(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    name: str,
) -> Agent | None:
    workspace_filter = (
        Agent.workspace_id.is_(None) if workspace_id is None else Agent.workspace_id == workspace_id
    )
    result = await session.execute(
        select(Agent).where(
            Agent.organization_id == organization_id,
            workspace_filter,
            Agent.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_agents(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    is_superuser: bool,
    workspace_id: uuid.UUID | None = None,
    include_inactive: bool = False,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[tuple[Agent, int, int]], str]:
    visible_statement = select(
        Agent.id.label("agent_id"),
        Agent.name.label("agent_name"),
    ).where(Agent.organization_id == organization_id)
    if workspace_id is not None:
        visible_statement = visible_statement.where(Agent.workspace_id == workspace_id)
    if not include_inactive:
        visible_statement = visible_statement.where(Agent.is_active.is_(True))
    if not is_superuser:
        visible_statement = (
            visible_statement.outerjoin(
                OrganizationMembership,
                and_(
                    OrganizationMembership.organization_id == Agent.organization_id,
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.is_active.is_(True),
                ),
            )
            .outerjoin(
                WorkspaceMembership,
                and_(
                    WorkspaceMembership.workspace_id == Agent.workspace_id,
                    WorkspaceMembership.user_id == user_id,
                    WorkspaceMembership.is_active.is_(True),
                ),
            )
            .where(
                or_(
                    Agent.workspace_id.is_(None),
                    OrganizationMembership.role.in_(ADMIN_ROLES),
                    WorkspaceMembership.id.is_not(None),
                )
            )
        )
    cursor_values = decode_cursor(cursor, fields=2)
    if cursor_values is not None:
        after_name, after_id_value = cursor_values
        try:
            after_id = uuid.UUID(after_id_value)
        except ValueError as exc:
            raise InvalidCursorError("invalid cursor") from exc
        visible_statement = visible_statement.where(
            or_(
                Agent.name > after_name,
                and_(Agent.name == after_name, Agent.id > after_id),
            )
        )
    visible_agents = (
        visible_statement.order_by(Agent.name.asc(), Agent.id.asc())
        .limit(limit + 1)
        .cte("visible_agents")
    )
    server_counts = (
        select(
            AgentMCPServerAssignment.agent_id.label("agent_id"),
            func.count(AgentMCPServerAssignment.id).label("server_count"),
        )
        .join(
            visible_agents,
            visible_agents.c.agent_id == AgentMCPServerAssignment.agent_id,
        )
        .group_by(AgentMCPServerAssignment.agent_id)
        .subquery()
    )
    explicit_tools = (
        select(
            AgentMCPServerAssignment.agent_id.label("agent_id"),
            MCPServerToolSchema.id.label("tool_schema_id"),
        )
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .join(
            MCPServerToolSchema,
            MCPServerToolSchema.id == AgentMCPToolAssignment.tool_schema_id,
        )
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == AgentMCPServerAssignment.installation_id,
        )
        .join(
            visible_agents,
            visible_agents.c.agent_id == AgentMCPServerAssignment.agent_id,
        )
        .where(
            AgentMCPToolAssignment.wildcard.is_(False),
            MCPServerToolSchema.is_active.is_(True),
            MCPServerInstallation.status == "enabled",
        )
    )
    wildcard_tools = (
        select(
            AgentMCPServerAssignment.agent_id.label("agent_id"),
            MCPServerToolSchema.id.label("tool_schema_id"),
        )
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == AgentMCPServerAssignment.installation_id,
        )
        .join(
            MCPServerToolSchema,
            MCPServerToolSchema.installation_id == MCPServerInstallation.id,
        )
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .join(
            visible_agents,
            visible_agents.c.agent_id == AgentMCPServerAssignment.agent_id,
        )
        .where(
            AgentMCPToolAssignment.wildcard.is_(True),
            MCPServerToolSchema.is_active.is_(True),
            MCPServerInstallation.status == "enabled",
        )
    )
    effective_tools = union_all(explicit_tools, wildcard_tools).subquery()
    tool_counts = (
        select(
            effective_tools.c.agent_id,
            func.count(func.distinct(effective_tools.c.tool_schema_id)).label("tool_count"),
        )
        .group_by(effective_tools.c.agent_id)
        .subquery()
    )
    statement = (
        select(
            Agent,
            func.coalesce(server_counts.c.server_count, 0),
            func.coalesce(tool_counts.c.tool_count, 0),
        )
        .join(visible_agents, visible_agents.c.agent_id == Agent.id)
        .outerjoin(server_counts, server_counts.c.agent_id == Agent.id)
        .outerjoin(tool_counts, tool_counts.c.agent_id == Agent.id)
        .order_by(visible_agents.c.agent_name.asc(), visible_agents.c.agent_id.asc())
    )
    result = await session.execute(statement)
    rows = [
        (agent, int(server_count), int(tool_count))
        for agent, server_count, tool_count in result.all()
    ]
    page = rows[:limit]
    next_cursor = ""
    if len(rows) > limit and page:
        last_agent = page[-1][0]
        next_cursor = encode_cursor(last_agent.name, str(last_agent.id))
    return page, next_cursor


async def list_active_workspace_agents(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[Agent]:
    result = await session.execute(
        select(Agent)
        .where(
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
        )
        .order_by(Agent.name.asc(), Agent.id.asc())
    )
    return list(result.scalars().all())


async def count_active_agents_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(Agent).where(
            Agent.organization_id == organization_id,
            Agent.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def count_active_agents_for_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(Agent).where(
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def count_active_agents_created_by_user_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(Agent).where(
            Agent.workspace_id == workspace_id,
            Agent.created_by_id == user_id,
            Agent.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def count_active_workspace_conversations(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(WorkspaceConversation).where(
            WorkspaceConversation.workspace_id == workspace_id,
            WorkspaceConversation.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def count_active_workspace_conversations_created_by_user(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(WorkspaceConversation).where(
            WorkspaceConversation.workspace_id == workspace_id,
            WorkspaceConversation.created_by_id == user_id,
            WorkspaceConversation.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def create_workspace_conversation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    created_by_id: uuid.UUID | None,
    title: str = "New chat",
) -> WorkspaceConversation:
    conversation = WorkspaceConversation(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        created_by_id=created_by_id,
        title=title,
        is_active=True,
    )
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return conversation


async def get_workspace_conversation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    include_inactive: bool = False,
) -> WorkspaceConversation | None:
    statement = select(WorkspaceConversation).where(
        WorkspaceConversation.id == conversation_id,
        WorkspaceConversation.organization_id == organization_id,
        WorkspaceConversation.workspace_id == workspace_id,
    )
    if not include_inactive:
        statement = statement.where(WorkspaceConversation.is_active.is_(True))
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_conversation_messages(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
) -> list[ConversationMessage]:
    result = await session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.sequence.asc())
    )
    return list(result.scalars().all())


async def latest_assistant_message_for_run(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> ConversationMessage | None:
    result = await session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.agent_run_id == agent_run_id,
            ConversationMessage.role == "assistant",
        )
        .order_by(ConversationMessage.sequence.desc(), ConversationMessage.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def append_conversation_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    parts: list[dict],
    agent_run_id: uuid.UUID | None = None,
) -> ConversationMessage:
    await session.execute(
        select(WorkspaceConversation.id)
        .where(WorkspaceConversation.id == conversation_id)
        .with_for_update()
    )
    result = await session.execute(
        select(func.max(ConversationMessage.sequence)).where(
            ConversationMessage.conversation_id == conversation_id
        )
    )
    sequence = (result.scalar_one_or_none() or 0) + 1
    message = ConversationMessage(
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        role=role,
        content=content,
        parts=parts,
        sequence=sequence,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return message


async def update_conversation_tool_activity(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    approval_id: uuid.UUID,
    data_update: dict,
) -> bool:
    messages = await list_conversation_messages(session, conversation_id=conversation_id)
    approval_id_text = str(approval_id)
    for message in messages:
        changed = False
        parts = []
        for part in message.parts:
            next_part = dict(part)
            data = next_part.get("data")
            approval = data.get("approval") if isinstance(data, dict) else None
            if isinstance(approval, dict) and approval.get("id") == approval_id_text:
                next_data = dict(data)
                next_approval = dict(approval)
                next_approval["status"] = data_update.get("status", next_approval.get("status"))
                next_data["approval"] = next_approval
                next_data.update(data_update)
                next_part["data"] = next_data
                changed = True
            parts.append(next_part)
        if changed:
            message.parts = parts
            flag_modified(message, "parts")
            await session.flush()
            return True
    return False


async def create_agent_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    triggered_by_id: uuid.UUID | None,
    previous_agent_run_id: uuid.UUID | None = None,
    trigger_type: str = "chat",
    now: datetime | None = None,
) -> AgentRun:
    now = now or datetime.now(UTC)
    agent_run = AgentRun(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        previous_agent_run_id=previous_agent_run_id,
        triggered_by_id=triggered_by_id,
        trigger_type=trigger_type,
        status="running",
        started_at=now,
        finished_at=None,
        error="",
    )
    session.add(agent_run)
    await session.flush()
    await session.refresh(agent_run)
    return agent_run


async def mark_agent_run_running(
    session: AsyncSession,
    agent_run: AgentRun,
) -> AgentRun:
    agent_run.status = "running"
    agent_run.error = ""
    agent_run.finished_at = None
    await session.flush()
    await session.refresh(agent_run)
    return agent_run


async def append_agent_run_step(
    session: AsyncSession,
    *,
    agent_run_id: uuid.UUID,
    step_type: str,
    status: str = "",
    title: str = "",
    payload: dict | None = None,
    mcp_tool_invocation_id: uuid.UUID | None = None,
) -> AgentRunStep:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == agent_run_id).with_for_update()
    )
    agent_run = result.scalar_one_or_none()
    if agent_run is not None:
        agent_run.updated_at = datetime.now(UTC)
    result = await session.execute(
        select(func.max(AgentRunStep.sequence)).where(AgentRunStep.agent_run_id == agent_run_id)
    )
    sequence = (result.scalar_one_or_none() or 0) + 1
    step = AgentRunStep(
        agent_run_id=agent_run_id,
        mcp_tool_invocation_id=mcp_tool_invocation_id,
        sequence=sequence,
        step_type=step_type,
        status=status,
        title=title,
        payload=payload or {},
    )
    session.add(step)
    await session.flush()
    await session.refresh(step)
    return step


async def create_tool_approval(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    agent_run_id: uuid.UUID | None,
    requested_by_id: uuid.UUID | None,
    installation_id: uuid.UUID,
    tool_schema_id: uuid.UUID,
    tool_call_id: str,
    tool_name: str,
    arguments: dict,
    expires_at: datetime | None = None,
) -> AgentToolApproval:
    approval = AgentToolApproval(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        requested_by_id=requested_by_id,
        decided_by_id=None,
        installation_id=installation_id,
        tool_schema_id=tool_schema_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        status="pending",
        result="",
        error="",
        expires_at=expires_at,
    )
    session.add(approval)
    await session.flush()
    await session.refresh(approval)
    return approval


async def get_tool_approval(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    for_update: bool = False,
) -> AgentToolApproval | None:
    statement = select(AgentToolApproval).where(
        AgentToolApproval.id == approval_id,
        AgentToolApproval.organization_id == organization_id,
        AgentToolApproval.workspace_id == workspace_id,
        AgentToolApproval.agent_id == agent_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_tool_approval_by_id(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    approval_id: uuid.UUID,
) -> AgentToolApproval | None:
    result = await session.execute(
        select(AgentToolApproval).where(
            AgentToolApproval.id == approval_id,
            AgentToolApproval.organization_id == organization_id,
            AgentToolApproval.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def latest_pending_tool_approval_by_conversation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> AgentToolApproval | None:
    result = await session.execute(
        select(AgentToolApproval)
        .where(
            AgentToolApproval.organization_id == organization_id,
            AgentToolApproval.workspace_id == workspace_id,
            AgentToolApproval.conversation_id == conversation_id,
            AgentToolApproval.status == "pending",
        )
        .order_by(AgentToolApproval.created_at.desc(), AgentToolApproval.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_expired_pending_tool_approvals(
    session: AsyncSession,
    *,
    now: datetime,
    fallback_created_before: datetime,
    trigger_type: str | None = None,
    limit: int = 100,
) -> list[AgentToolApproval]:
    statement = select(AgentToolApproval)
    if trigger_type is not None:
        statement = statement.join(AgentRun, AgentRun.id == AgentToolApproval.agent_run_id)
    statement = statement.where(
        AgentToolApproval.status == "pending",
        or_(
            AgentToolApproval.expires_at <= now,
            and_(
                AgentToolApproval.expires_at.is_(None),
                AgentToolApproval.created_at <= fallback_created_before,
            ),
        ),
    )
    if trigger_type is not None:
        statement = statement.where(AgentRun.trigger_type == trigger_type)
    result = await session.execute(
        statement.order_by(
            AgentToolApproval.expires_at.asc().nulls_last(),
            AgentToolApproval.created_at.asc(),
            AgentToolApproval.id.asc(),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def list_expired_active_tool_approvals(
    session: AsyncSession,
    *,
    now: datetime,
    fallback_created_before: datetime,
    trigger_type: str | None = None,
    limit: int = 100,
) -> list[AgentToolApproval]:
    statement = select(AgentToolApproval)
    if trigger_type is not None:
        statement = statement.join(AgentRun, AgentRun.id == AgentToolApproval.agent_run_id)
    statement = statement.where(
        AgentToolApproval.status.in_(("pending", "running")),
        or_(
            AgentToolApproval.expires_at <= now,
            and_(
                AgentToolApproval.expires_at.is_(None),
                AgentToolApproval.created_at <= fallback_created_before,
            ),
        ),
    )
    if trigger_type is not None:
        statement = statement.where(AgentRun.trigger_type == trigger_type)
    result = await session.execute(
        statement.order_by(
            AgentToolApproval.expires_at.asc().nulls_last(),
            AgentToolApproval.created_at.asc(),
            AgentToolApproval.id.asc(),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def list_active_tool_approvals_for_agent_run(
    session: AsyncSession,
    *,
    agent_run_id: uuid.UUID,
) -> list[AgentToolApproval]:
    result = await session.execute(
        select(AgentToolApproval)
        .where(
            AgentToolApproval.agent_run_id == agent_run_id,
            AgentToolApproval.status.in_(("pending", "running")),
        )
        .order_by(AgentToolApproval.created_at.asc(), AgentToolApproval.id.asc())
        .with_for_update()
    )
    return list(result.scalars().all())


async def has_completed_tool_approval_for_agent_run(
    session: AsyncSession,
    *,
    agent_run_id: uuid.UUID,
    installation_id: uuid.UUID,
    tool_schema_id: uuid.UUID,
    decided_by_id: uuid.UUID | None = None,
) -> bool:
    statement = (
        select(AgentToolApproval.id)
        .where(
            AgentToolApproval.agent_run_id == agent_run_id,
            AgentToolApproval.installation_id == installation_id,
            AgentToolApproval.tool_schema_id == tool_schema_id,
            AgentToolApproval.status == "completed",
        )
        .limit(1)
    )
    if decided_by_id is not None:
        statement = statement.where(AgentToolApproval.decided_by_id == decided_by_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None


async def enqueue_agent_run_resume_job(
    session: AsyncSession,
    *,
    approval: AgentToolApproval,
    user_id: uuid.UUID | None,
    now: datetime | None = None,
    max_attempts: int = 3,
) -> AgentRunResumeJob | None:
    if approval.agent_run_id is None:
        return None
    now = now or datetime.now(UTC)
    result = await session.execute(
        select(AgentRunResumeJob)
        .where(
            AgentRunResumeJob.approval_id == approval.id,
            AgentRunResumeJob.status.in_(("queued", "running")),
        )
        .with_for_update(skip_locked=True)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    job = AgentRunResumeJob(
        organization_id=approval.organization_id,
        workspace_id=approval.workspace_id,
        agent_id=approval.agent_id,
        agent_run_id=approval.agent_run_id,
        approval_id=approval.id,
        user_id=user_id,
        status="queued",
        available_at=now,
        started_at=None,
        finished_at=None,
        attempt_count=0,
        max_attempts=max_attempts,
        worker_id="",
        lease_expires_at=None,
        error="",
        payload={"toolName": approval.tool_name},
    )
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def claim_next_agent_run_resume_job(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> AgentRunResumeJob | None:
    result = await session.execute(
        select(AgentRunResumeJob)
        .where(
            AgentRunResumeJob.status == "queued",
            AgentRunResumeJob.available_at <= now,
        )
        .order_by(
            AgentRunResumeJob.available_at.asc(),
            AgentRunResumeJob.created_at.asc(),
            AgentRunResumeJob.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.worker_id = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.finished_at = None
    job.error = ""
    await session.flush()
    await session.refresh(job)
    return job


async def heartbeat_agent_run_resume_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    lease_expires_at: datetime,
) -> bool:
    result = await session.execute(
        update(AgentRunResumeJob)
        .where(
            AgentRunResumeJob.id == job_id,
            AgentRunResumeJob.status == "running",
            AgentRunResumeJob.worker_id == worker_id,
        )
        .values(lease_expires_at=lease_expires_at)
    )
    return result.rowcount == 1


async def get_owned_agent_run_resume_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
) -> AgentRunResumeJob | None:
    result = await session.execute(
        select(AgentRunResumeJob)
        .where(
            AgentRunResumeJob.id == job_id,
            AgentRunResumeJob.status == "running",
            AgentRunResumeJob.worker_id == worker_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def complete_agent_run_resume_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    now: datetime,
) -> bool:
    job = await get_owned_agent_run_resume_job(session, job_id, worker_id=worker_id)
    if job is None:
        return False
    job.status = "succeeded"
    job.finished_at = now
    job.worker_id = ""
    job.lease_expires_at = None
    job.error = ""
    await session.flush()
    return True


async def retry_or_fail_agent_run_resume_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    now: datetime,
    retry_at: datetime,
    error_message: str,
) -> str | None:
    job = await get_owned_agent_run_resume_job(session, job_id, worker_id=worker_id)
    if job is None:
        return None
    retryable = job.attempt_count < job.max_attempts
    job.worker_id = ""
    job.lease_expires_at = None
    job.error = error_message
    if retryable:
        job.status = "queued"
        job.available_at = retry_at
        job.finished_at = None
    else:
        job.status = "failed"
        job.finished_at = now
    await session.flush()
    return job.status


async def recover_expired_agent_run_resume_jobs(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> int:
    result = await session.execute(
        select(AgentRunResumeJob)
        .where(
            AgentRunResumeJob.status == "running",
            AgentRunResumeJob.lease_expires_at <= now,
        )
        .order_by(AgentRunResumeJob.lease_expires_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    recovered = 0
    for job in result.scalars().all():
        retryable = job.attempt_count < job.max_attempts
        job.status = "queued" if retryable else "failed"
        job.available_at = now
        job.finished_at = None if retryable else now
        job.worker_id = ""
        job.lease_expires_at = None
        job.error = "The agent run resume worker stopped renewing its lease"
        recovered += 1
    await session.flush()
    return recovered


async def enqueue_stale_agent_run_resume_jobs(
    session: AsyncSession,
    *,
    now: datetime,
    stale_before: datetime,
    limit: int = 50,
) -> int:
    active_resume_job_exists = (
        select(AgentRunResumeJob.id)
        .where(
            AgentRunResumeJob.approval_id == AgentToolApproval.id,
            AgentRunResumeJob.status.in_(("queued", "running")),
        )
        .exists()
    )
    result = await session.execute(
        select(AgentToolApproval)
        .join(AgentRun, AgentRun.id == AgentToolApproval.agent_run_id)
        .where(
            AgentRun.status == "running",
            AgentRun.updated_at <= stale_before,
            AgentToolApproval.status.in_(("running", "completed")),
            AgentToolApproval.updated_at <= stale_before,
            AgentToolApproval.decided_by_id.is_not(None),
            ~active_resume_job_exists,
        )
        .order_by(AgentToolApproval.updated_at.asc(), AgentToolApproval.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    enqueued = 0
    for approval in result.scalars().all():
        job = await enqueue_agent_run_resume_job(
            session,
            approval=approval,
            user_id=approval.decided_by_id,
            now=now,
        )
        if job is not None and job.status == "queued":
            enqueued += 1
    return enqueued


async def fail_stale_orphaned_agent_runs(
    session: AsyncSession,
    *,
    now: datetime,
    stale_before: datetime,
    limit: int = 50,
) -> int:
    active_resume_job_exists = (
        select(AgentRunResumeJob.id)
        .where(
            AgentRunResumeJob.agent_run_id == AgentRun.id,
            AgentRunResumeJob.status.in_(("queued", "running")),
        )
        .exists()
    )
    active_approval_exists = (
        select(AgentToolApproval.id)
        .where(
            AgentToolApproval.agent_run_id == AgentRun.id,
            AgentToolApproval.status.in_(("pending", "running", "completed")),
        )
        .exists()
    )
    result = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.status == "running",
            AgentRun.updated_at <= stale_before,
            ~active_resume_job_exists,
            ~active_approval_exists,
        )
        .order_by(AgentRun.updated_at.asc(), AgentRun.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    failed = 0
    error = (
        "The run was abandoned by a worker restart or shutdown and cannot be "
        "safely resumed from its last in-memory execution state."
    )
    for agent_run in result.scalars().all():
        await append_agent_run_step(
            session,
            agent_run_id=agent_run.id,
            step_type="run_recovery_failed",
            status="failed",
            title="Run abandoned",
            payload={"error": error},
        )
        await finish_agent_run(
            session,
            agent_run,
            status="failed",
            error=error,
            now=now,
        )
        failed += 1
    return failed


async def finish_agent_run(
    session: AsyncSession,
    agent_run: AgentRun,
    *,
    status: str,
    error: str = "",
    now: datetime | None = None,
) -> AgentRun:
    if agent_run.status == "canceled" and status != "canceled":
        await session.refresh(agent_run)
        return agent_run
    agent_run.status = status
    agent_run.error = error
    agent_run.finished_at = now or datetime.now(UTC)
    await session.flush()
    await session.refresh(agent_run)
    return agent_run


async def list_agent_runs(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    limit: int = 50,
) -> list[AgentRun]:
    result = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.workspace_id == workspace_id,
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_agent_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
    for_update: bool = False,
) -> AgentRun | None:
    statement = select(AgentRun).where(
        AgentRun.id == agent_run_id,
        AgentRun.organization_id == organization_id,
        AgentRun.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def latest_agent_run_for_conversation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    trigger_type: str | None = None,
) -> AgentRun | None:
    statement = select(AgentRun).where(
        AgentRun.organization_id == organization_id,
        AgentRun.workspace_id == workspace_id,
        AgentRun.conversation_id == conversation_id,
    )
    if trigger_type is not None:
        statement = statement.where(AgentRun.trigger_type == trigger_type)
    result = await session.execute(
        statement.order_by(
            AgentRun.started_at.desc(),
            AgentRun.created_at.desc(),
            AgentRun.id.desc(),
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def list_agent_run_steps(
    session: AsyncSession,
    *,
    agent_run_id: uuid.UUID,
) -> list[AgentRunStep]:
    result = await session.execute(
        select(AgentRunStep)
        .where(AgentRunStep.agent_run_id == agent_run_id)
        .order_by(AgentRunStep.sequence.asc())
    )
    return list(result.scalars().all())


async def list_recent_workspace_agent_run_steps(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    limit: int = 250,
) -> list[tuple[AgentRunStep, AgentRun, Agent]]:
    result = await session.execute(
        select(AgentRunStep, AgentRun, Agent)
        .join(AgentRun, AgentRunStep.agent_run_id == AgentRun.id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.workspace_id == workspace_id,
        )
        .order_by(AgentRunStep.created_at.desc(), AgentRunStep.sequence.desc())
        .limit(limit)
    )
    return list(result.all())


async def list_workspace_approved_skills(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    include_inactive: bool = False,
) -> list[WorkspaceApprovedSkill]:
    statement = select(WorkspaceApprovedSkill).where(
        WorkspaceApprovedSkill.organization_id == organization_id,
        WorkspaceApprovedSkill.workspace_id == workspace_id,
    )
    if not include_inactive:
        statement = statement.where(WorkspaceApprovedSkill.status == "active")
    result = await session.execute(
        statement.order_by(
            WorkspaceApprovedSkill.name.asc(),
            WorkspaceApprovedSkill.skill_id.asc(),
        )
    )
    return list(result.scalars().all())


async def get_workspace_approved_skill(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    workspace_skill_id: uuid.UUID,
) -> WorkspaceApprovedSkill | None:
    result = await session.execute(
        select(WorkspaceApprovedSkill).where(
            WorkspaceApprovedSkill.id == workspace_skill_id,
            WorkspaceApprovedSkill.organization_id == organization_id,
            WorkspaceApprovedSkill.workspace_id == workspace_id,
            WorkspaceApprovedSkill.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_workspace_approved_skill_by_skill_id(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    skill_id: str,
) -> WorkspaceApprovedSkill | None:
    result = await session.execute(
        select(WorkspaceApprovedSkill).where(
            WorkspaceApprovedSkill.organization_id == organization_id,
            WorkspaceApprovedSkill.workspace_id == workspace_id,
            WorkspaceApprovedSkill.skill_id == skill_id,
            WorkspaceApprovedSkill.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def list_workspace_approved_skill_assignments(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[tuple[WorkspaceApprovedSkill, AgentApprovedSkillAssignment, Agent]]:
    result = await session.execute(
        select(WorkspaceApprovedSkill, AgentApprovedSkillAssignment, Agent)
        .join(
            AgentApprovedSkillAssignment,
            AgentApprovedSkillAssignment.workspace_skill_id == WorkspaceApprovedSkill.id,
        )
        .join(Agent, Agent.id == AgentApprovedSkillAssignment.agent_id)
        .where(
            WorkspaceApprovedSkill.organization_id == organization_id,
            WorkspaceApprovedSkill.workspace_id == workspace_id,
            WorkspaceApprovedSkill.status == "active",
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
        )
        .order_by(WorkspaceApprovedSkill.skill_id.asc(), Agent.name.asc(), Agent.id.asc())
    )
    return list(result.all())


async def list_agent_approved_skills(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> list[WorkspaceApprovedSkill]:
    active_agent_exists = (
        select(Agent.id)
        .where(
            Agent.id == agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
        )
        .exists()
    )
    result = await session.execute(
        select(WorkspaceApprovedSkill)
        .where(
            WorkspaceApprovedSkill.organization_id == organization_id,
            WorkspaceApprovedSkill.workspace_id == workspace_id,
            WorkspaceApprovedSkill.status == "active",
            active_agent_exists,
        )
        .order_by(WorkspaceApprovedSkill.name.asc(), WorkspaceApprovedSkill.skill_id.asc())
    )
    return list(result.scalars().all())


async def replace_workspace_approved_skill_assignments(
    session: AsyncSession,
    *,
    workspace_skill_id: uuid.UUID,
    agents: list[Agent],
) -> None:
    await session.execute(
        delete(AgentApprovedSkillAssignment).where(
            AgentApprovedSkillAssignment.workspace_skill_id == workspace_skill_id
        )
    )
    await session.flush()
    for agent in agents:
        session.add(
            AgentApprovedSkillAssignment(
                agent_id=agent.id,
                workspace_skill_id=workspace_skill_id,
            )
        )
    await session.flush()


async def delete_workspace_approved_skill(
    session: AsyncSession,
    *,
    workspace_skill: WorkspaceApprovedSkill,
) -> None:
    await session.delete(workspace_skill)
    await session.flush()


async def list_chat_provider_triggers_by_conversation(
    session: AsyncSession,
    *,
    conversation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    if not conversation_ids:
        return {}
    result = await session.execute(
        select(ChatProviderThread.conversation_id, ChatProviderConnection.provider)
        .join(
            ChatProviderConnection,
            ChatProviderConnection.id == ChatProviderThread.connection_id,
        )
        .where(ChatProviderThread.conversation_id.in_(conversation_ids))
    )
    return {
        conversation_id: provider
        for conversation_id, provider in result.all()
        if conversation_id is not None
    }


async def list_workspace_available_tools(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> list[tuple[MCPServerToolSchema, MCPServerInstallation]]:
    result = await session.execute(
        select(MCPServerToolSchema, MCPServerInstallation)
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == MCPServerToolSchema.installation_id,
        )
        .where(
            MCPServerToolSchema.workspace_id == workspace_id,
            MCPServerToolSchema.is_active.is_(True),
            MCPServerInstallation.workspace_id == workspace_id,
            MCPServerInstallation.status == "enabled",
        )
        .order_by(
            MCPServerToolSchema.server_name.asc(),
            MCPServerInstallation.config_name.asc(),
            MCPServerToolSchema.tool_name.asc(),
        )
    )
    return list(result.all())


async def count_agent_tools(session: AsyncSession, agent_id: uuid.UUID) -> int:
    rows = await list_agent_tools(session, agent_id=agent_id)
    return len({tool_schema.id for _assignment, tool_schema, _installation in rows})


async def count_agent_servers(session: AsyncSession, agent_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(AgentMCPServerAssignment).where(
            AgentMCPServerAssignment.agent_id == agent_id
        )
    )
    return int(result.scalar_one())


async def replace_agent_tools(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    server_assignments: list[tuple[MCPServerInstallation, bool, list[MCPServerToolSchema]]],
) -> None:
    await session.execute(
        delete(AgentMCPServerAssignment).where(AgentMCPServerAssignment.agent_id == agent_id)
    )
    await session.flush()
    for installation, wildcard, tool_schemas in server_assignments:
        server_assignment = AgentMCPServerAssignment(
            agent_id=agent_id,
            installation_id=installation.id,
        )
        session.add(server_assignment)
        await session.flush()
        if wildcard:
            session.add(
                AgentMCPToolAssignment(
                    server_assignment_id=server_assignment.id,
                    tool_schema_id=None,
                    wildcard=True,
                )
            )
            continue
        for tool_schema in tool_schemas:
            session.add(
                AgentMCPToolAssignment(
                    server_assignment_id=server_assignment.id,
                    tool_schema_id=tool_schema.id,
                    wildcard=False,
                )
            )
    await session.flush()


async def list_agent_tools(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
) -> list[tuple[AgentMCPServerAssignment, MCPServerToolSchema, MCPServerInstallation]]:
    explicit_result = await session.execute(
        select(AgentMCPServerAssignment, MCPServerToolSchema, MCPServerInstallation)
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .join(
            MCPServerToolSchema,
            MCPServerToolSchema.id == AgentMCPToolAssignment.tool_schema_id,
        )
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == AgentMCPServerAssignment.installation_id,
        )
        .where(
            AgentMCPServerAssignment.agent_id == agent_id,
            AgentMCPToolAssignment.wildcard.is_(False),
            MCPServerToolSchema.is_active.is_(True),
            MCPServerInstallation.status == "enabled",
        )
    )
    wildcard_result = await session.execute(
        select(AgentMCPServerAssignment, MCPServerToolSchema, MCPServerInstallation)
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == AgentMCPServerAssignment.installation_id,
        )
        .join(MCPServerToolSchema, MCPServerToolSchema.installation_id == MCPServerInstallation.id)
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .where(
            AgentMCPServerAssignment.agent_id == agent_id,
            AgentMCPToolAssignment.wildcard.is_(True),
            MCPServerToolSchema.is_active.is_(True),
            MCPServerInstallation.status == "enabled",
        )
    )
    rows = list(explicit_result.all()) + list(wildcard_result.all())
    return sorted(rows, key=lambda row: (row[2].server_name, row[2].config_name, row[1].tool_name))


async def list_agent_tool_runtime_rows(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
) -> list[
    tuple[
        AgentMCPServerAssignment,
        MCPServerToolSchema,
        MCPServerInstallation,
        MCPServerVersion,
    ]
]:
    tool_rows = await list_agent_tools(session, agent_id=agent_id)
    version_keys = {
        (
            installation.workspace_id,
            installation.server_name,
            installation.installed_version,
        )
        for _assignment, _tool_schema, installation in tool_rows
    }
    if not version_keys:
        return []
    version_result = await session.execute(
        select(Workspace.id, MCPServerVersion)
        .join(
            MCPServerVersion,
            MCPServerVersion.organization_id == Workspace.organization_id,
        )
        .where(
            or_(
                *[
                    and_(
                        Workspace.id == workspace_id,
                        MCPServerVersion.name == server_name,
                        MCPServerVersion.version == installed_version,
                    )
                    for workspace_id, server_name, installed_version in version_keys
                ]
            )
        )
    )
    versions = {
        (workspace_id, version.name, version.version): version
        for workspace_id, version in version_result.all()
    }
    return [
        (
            assignment,
            tool_schema,
            installation,
            versions[
                (
                    installation.workspace_id,
                    installation.server_name,
                    installation.installed_version,
                )
            ],
        )
        for assignment, tool_schema, installation in tool_rows
        if (
            installation.workspace_id,
            installation.server_name,
            installation.installed_version,
        )
        in versions
    ]


async def list_agent_wildcard_server_version_rows(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
) -> list[tuple[AgentMCPServerAssignment, MCPServerInstallation, MCPServerVersion]]:
    result = await session.execute(
        select(AgentMCPServerAssignment, MCPServerInstallation, MCPServerVersion)
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == AgentMCPServerAssignment.installation_id,
        )
        .join(
            MCPServerVersion,
            and_(
                MCPServerVersion.name == MCPServerInstallation.server_name,
                MCPServerVersion.version == MCPServerInstallation.installed_version,
            ),
        )
        .where(
            AgentMCPServerAssignment.agent_id == agent_id,
            AgentMCPToolAssignment.wildcard.is_(True),
            MCPServerInstallation.status == "enabled",
        )
        .order_by(MCPServerInstallation.server_name.asc(), MCPServerInstallation.config_name.asc())
    )
    return list(result.all())
