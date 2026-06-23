import uuid

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent, AgentTool
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerToolSchema
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
    include_inactive: bool = False,
) -> Agent | None:
    statement = select(Agent).where(
        Agent.id == agent_id,
        Agent.organization_id == organization_id,
    )
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
    include_inactive: bool = False,
) -> list[tuple[Agent, int]]:
    statement = (
        select(Agent, func.count(AgentTool.id).label("tool_count"))
        .outerjoin(AgentTool, AgentTool.agent_id == Agent.id)
        .where(Agent.organization_id == organization_id)
        .group_by(Agent.id)
        .order_by(Agent.name.asc())
    )
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
    return [(agent, int(tool_count)) for agent, tool_count in result.all()]


async def count_agent_tools(session: AsyncSession, agent_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(AgentTool).where(AgentTool.agent_id == agent_id)
    )
    return int(result.scalar_one())


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
    tool_rows: list[tuple[MCPServerToolSchema, MCPServerInstallation, Workspace]],
) -> None:
    await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
    for tool_schema, installation, _workspace in tool_rows:
        session.add(
            AgentTool(
                agent_id=agent_id,
                tool_schema_id=tool_schema.id,
                installation_id=installation.id,
            )
        )
    await session.flush()


async def list_agent_tools(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
) -> list[tuple[AgentTool, MCPServerToolSchema, MCPServerInstallation]]:
    result = await session.execute(
        select(AgentTool, MCPServerToolSchema, MCPServerInstallation)
        .join(MCPServerToolSchema, MCPServerToolSchema.id == AgentTool.tool_schema_id)
        .join(MCPServerInstallation, MCPServerInstallation.id == AgentTool.installation_id)
        .where(AgentTool.agent_id == agent_id)
        .order_by(MCPServerToolSchema.server_name.asc(), MCPServerToolSchema.tool_name.asc())
    )
    return list(result.all())

