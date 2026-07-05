import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardrails.models import GuardrailPolicy


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
) -> list[GuardrailPolicy]:
    statement = select(GuardrailPolicy).where(
        GuardrailPolicy.organization_id == organization_id,
        GuardrailPolicy.workspace_id == workspace_id,
        GuardrailPolicy.is_active.is_(True),
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


async def delete_policies_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
) -> None:
    await session.execute(
        delete(GuardrailPolicy).where(GuardrailPolicy.workspace_id == workspace_id)
    )
