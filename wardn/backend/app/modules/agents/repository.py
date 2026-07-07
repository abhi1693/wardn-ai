import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.modules.agents.models import (
    Agent,
    AgentMCPServerAssignment,
    AgentMCPToolAssignment,
    AgentRun,
    AgentRunStep,
    AgentToolApproval,
    ConversationMessage,
    WorkspaceConversation,
)
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
) -> list[tuple[Agent, int, int]]:
    statement = (
        select(Agent)
        .where(Agent.organization_id == organization_id)
        .order_by(Agent.name.asc())
    )
    if workspace_id is not None:
        statement = statement.where(Agent.workspace_id == workspace_id)
    if not include_inactive:
        statement = statement.where(Agent.is_active.is_(True))
    if not is_superuser:
        statement = (
            statement.outerjoin(
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
    result = await session.execute(statement)
    agents = list(result.scalars().all())
    return [
        (
            agent,
            await count_agent_servers(session, agent.id),
            await count_agent_tools(session, agent.id),
        )
        for agent in agents
    ]


async def count_active_agents_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    if not hasattr(session, "execute"):
        return 0
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
    if not hasattr(session, "execute"):
        return 0
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
    if not hasattr(session, "execute"):
        return 0
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
    if not hasattr(session, "execute"):
        return 0
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
    if not hasattr(session, "execute"):
        return 0
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


async def append_conversation_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    parts: list[dict],
    agent_run_id: uuid.UUID | None = None,
) -> ConversationMessage:
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
    trigger_type: str = "chat",
    now: datetime | None = None,
) -> AgentRun:
    now = now or datetime.now(UTC)
    agent_run = AgentRun(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
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
) -> AgentToolApproval | None:
    result = await session.execute(
        select(AgentToolApproval).where(
            AgentToolApproval.id == approval_id,
            AgentToolApproval.organization_id == organization_id,
            AgentToolApproval.workspace_id == workspace_id,
            AgentToolApproval.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none()


async def finish_agent_run(
    session: AsyncSession,
    agent_run: AgentRun,
    *,
    status: str,
    error: str = "",
    now: datetime | None = None,
) -> AgentRun:
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
) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.id == agent_run_id,
            AgentRun.organization_id == organization_id,
            AgentRun.workspace_id == workspace_id,
        )
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


async def get_installations_by_ids(
    session: AsyncSession,
    installation_ids: list[uuid.UUID],
) -> list[tuple[MCPServerInstallation, Workspace]]:
    if not installation_ids:
        return []
    result = await session.execute(
        select(MCPServerInstallation, Workspace)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .where(
            MCPServerInstallation.id.in_(installation_ids),
            MCPServerInstallation.status == "enabled",
        )
    )
    return list(result.all())


async def get_tool_schemas_by_ids(
    session: AsyncSession,
    tool_schema_ids: list[uuid.UUID],
) -> list[tuple[MCPServerToolSchema, MCPServerInstallation, Workspace]]:
    if not tool_schema_ids:
        return []
    result = await session.execute(
        select(MCPServerToolSchema, MCPServerInstallation, Workspace)
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == MCPServerToolSchema.installation_id,
        )
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .where(
            MCPServerToolSchema.id.in_(tool_schema_ids),
            MCPServerToolSchema.is_active.is_(True),
            MCPServerToolSchema.installation_id.is_not(None),
            MCPServerInstallation.status == "enabled",
        )
    )
    return list(result.all())


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


async def list_agent_server_assignments(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
) -> list[tuple[AgentMCPServerAssignment, AgentMCPToolAssignment]]:
    result = await session.execute(
        select(AgentMCPServerAssignment, AgentMCPToolAssignment)
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .where(AgentMCPServerAssignment.agent_id == agent_id)
        .order_by(
            AgentMCPServerAssignment.created_at.asc(),
            AgentMCPToolAssignment.created_at.asc(),
        )
    )
    return list(result.all())


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
        (installation.server_name, installation.installed_version)
        for _assignment, _tool_schema, installation in tool_rows
    }
    if not version_keys:
        return []
    version_result = await session.execute(
        select(MCPServerVersion).where(
            or_(
                *[
                    and_(
                        MCPServerVersion.name == server_name,
                        MCPServerVersion.version == installed_version,
                    )
                    for server_name, installed_version in version_keys
                ]
            )
        )
    )
    versions = {
        (version.name, version.version): version
        for version in version_result.scalars().all()
    }
    return [
        (
            assignment,
            tool_schema,
            installation,
            versions[(installation.server_name, installation.installed_version)],
        )
        for assignment, tool_schema, installation in tool_rows
        if (installation.server_name, installation.installed_version) in versions
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
