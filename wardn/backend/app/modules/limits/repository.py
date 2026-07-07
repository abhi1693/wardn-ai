import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.models import ResourceLimit


async def list_limits(
    session: AsyncSession,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    limit_key: str | None = None,
) -> list[ResourceLimit]:
    statement = select(ResourceLimit).order_by(
        ResourceLimit.scope_type.asc(),
        ResourceLimit.limit_key.asc(),
        ResourceLimit.created_at.asc(),
    )
    if scope_type is not None:
        statement = statement.where(ResourceLimit.scope_type == scope_type)
    if scope_id is not None:
        statement = statement.where(ResourceLimit.scope_id == scope_id)
    if limit_key is not None:
        statement = statement.where(ResourceLimit.limit_key == limit_key)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_limit_by_id(
    session: AsyncSession,
    limit_id: uuid.UUID,
) -> ResourceLimit | None:
    return await session.get(ResourceLimit, limit_id)


async def get_limit(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: uuid.UUID,
    limit_key: str,
) -> ResourceLimit | None:
    result = await session.execute(
        select(ResourceLimit).where(
            ResourceLimit.scope_type == scope_type,
            ResourceLimit.scope_id == scope_id,
            ResourceLimit.limit_key == limit_key,
        )
    )
    return result.scalar_one_or_none()
