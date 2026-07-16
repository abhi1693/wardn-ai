import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.secrets.models import ManagedSecret, SecretHandle, SecretStore


async def list_stores(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> list[SecretStore]:
    statement = (
        select(SecretStore)
        .where(SecretStore.organization_id == organization_id)
        .order_by(SecretStore.workspace_id.asc().nullsfirst(), SecretStore.name.asc())
    )
    if workspace_id is not None:
        statement = statement.where(
            (SecretStore.workspace_id == workspace_id) | (SecretStore.workspace_id.is_(None))
        )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_store(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    store_id: uuid.UUID,
) -> SecretStore | None:
    result = await session.execute(
        select(SecretStore).where(
            SecretStore.id == store_id,
            SecretStore.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_store_by_name(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    name: str,
) -> SecretStore | None:
    statement = select(SecretStore).where(
        SecretStore.organization_id == organization_id,
        SecretStore.name == name,
    )
    if workspace_id is None:
        statement = statement.where(SecretStore.workspace_id.is_(None))
    else:
        statement = statement.where(SecretStore.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def count_stores_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(SecretStore).where(
            SecretStore.organization_id == organization_id,
        )
    )
    return int(result.scalar_one())


async def count_stores_for_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(SecretStore).where(
            SecretStore.workspace_id == workspace_id,
        )
    )
    return int(result.scalar_one())


async def has_managed_secrets_for_store(
    session: AsyncSession,
    store_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        select(
            select(ManagedSecret.id)
            .where(ManagedSecret.store_id == store_id)
            .limit(1)
            .exists()
        )
    )
    return bool(result.scalar_one())


async def list_handles(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> list[SecretHandle]:
    statement = (
        select(SecretHandle)
        .where(SecretHandle.organization_id == organization_id)
        .order_by(SecretHandle.workspace_id.asc().nullsfirst(), SecretHandle.display_name.asc())
    )
    if workspace_id is not None:
        statement = statement.where(
            (SecretHandle.workspace_id == workspace_id) | (SecretHandle.workspace_id.is_(None))
        )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_handle(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID,
) -> SecretHandle | None:
    result = await session.execute(
        select(SecretHandle).where(
            SecretHandle.id == handle_id,
            SecretHandle.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def count_handles_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(SecretHandle).where(
            SecretHandle.organization_id == organization_id,
        )
    )
    return int(result.scalar_one())


async def count_handles_for_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(SecretHandle).where(
            SecretHandle.workspace_id == workspace_id,
        )
    )
    return int(result.scalar_one())


async def get_handle_by_display_name(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    display_name: str,
) -> SecretHandle | None:
    statement = select(SecretHandle).where(
        SecretHandle.organization_id == organization_id,
        SecretHandle.display_name == display_name,
    )
    if workspace_id is None:
        statement = statement.where(SecretHandle.workspace_id.is_(None))
    else:
        statement = statement.where(SecretHandle.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()
