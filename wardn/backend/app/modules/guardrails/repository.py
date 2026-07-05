import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardrails.models import GuardrailPolicy
from app.modules.mcp_registry.models import MCPServerToolSchema


async def list_policies(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[GuardrailPolicy]:
    statement = select(GuardrailPolicy).where(
        GuardrailPolicy.organization_id == organization_id,
        GuardrailPolicy.workspace_id == workspace_id,
    )
    result = await session.execute(
        statement.order_by(
            GuardrailPolicy.priority.asc(),
            GuardrailPolicy.name.asc(),
        )
    )
    return list(result.scalars().all())


async def get_policy(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    policy_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> GuardrailPolicy | None:
    statement = select(GuardrailPolicy).where(
        GuardrailPolicy.id == policy_id,
        GuardrailPolicy.organization_id == organization_id,
        GuardrailPolicy.workspace_id == workspace_id,
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_policy_by_name(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    name: str,
) -> GuardrailPolicy | None:
    statement = select(GuardrailPolicy).where(
        GuardrailPolicy.organization_id == organization_id,
        GuardrailPolicy.workspace_id == workspace_id,
        GuardrailPolicy.name == name,
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_matching_policies(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    installation_id: uuid.UUID,
    tool_schema_id: uuid.UUID | None,
    include_agent_scoped: bool = False,
) -> list[GuardrailPolicy]:
    statement = select(GuardrailPolicy).where(
        GuardrailPolicy.organization_id == organization_id,
        GuardrailPolicy.workspace_id == workspace_id,
        GuardrailPolicy.is_active.is_(True),
        or_(
            GuardrailPolicy.installation_id.is_(None),
            GuardrailPolicy.installation_id == installation_id,
        ),
        or_(
            GuardrailPolicy.tool_schema_id.is_(None),
            GuardrailPolicy.tool_schema_id == tool_schema_id,
        ),
    )
    if not include_agent_scoped:
        statement = statement.where(
            or_(
                GuardrailPolicy.agent_id.is_(None),
                GuardrailPolicy.agent_id == agent_id,
            )
        )
    result = await session.execute(
        statement.order_by(
            GuardrailPolicy.priority.asc(),
            GuardrailPolicy.created_at.asc(),
        )
    )
    return list(result.scalars().all())


async def delete_policy(session: AsyncSession, policy: GuardrailPolicy) -> None:
    await session.delete(policy)


async def get_tool_schema(
    session: AsyncSession,
    *,
    tool_schema_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerToolSchema | None:
    statement = select(MCPServerToolSchema).where(MCPServerToolSchema.id == tool_schema_id)
    if workspace_id is not None:
        statement = statement.where(MCPServerToolSchema.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def delete_policies_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> None:
    await session.execute(
        delete(GuardrailPolicy).where(GuardrailPolicy.workspace_id == workspace_id)
    )
