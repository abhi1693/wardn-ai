import uuid

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent, AgentMCPServerAssignment, AgentMCPToolAssignment
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
    name: str,
) -> Agent | None:
    result = await session.execute(
        select(Agent).where(
            Agent.organization_id == organization_id,
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
) -> list[tuple[Agent, int]]:
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
    return [(agent, await count_agent_tools(session, agent.id)) for agent in agents]


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
