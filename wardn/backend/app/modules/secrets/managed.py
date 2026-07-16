import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.modules.secrets import managed_repository
from app.modules.secrets.models import ManagedSecret, SecretHandle


async def persist_managed_secret_intent(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    store_id: uuid.UUID,
    created_by_id: uuid.UUID | None,
    owner_type: str,
    owner_id: uuid.UUID,
    purpose: str,
    external_ref: str,
    session_factory=AsyncSessionLocal,
) -> uuid.UUID:
    """Commit recovery state before an external write can succeed."""
    managed_secret = ManagedSecret(
        organization_id=organization_id,
        workspace_id=workspace_id,
        store_id=store_id,
        created_by_id=created_by_id,
        owner_type=owner_type,
        owner_id=owner_id,
        purpose=purpose,
        external_ref=external_ref,
        status="provisioning",
        cleanup_available_at=datetime.now(UTC),
    )
    async with session_factory() as lifecycle_session:
        lifecycle_session.add(managed_secret)
        await lifecycle_session.commit()
        return managed_secret.id


async def activate_managed_secret(
    session: AsyncSession,
    managed_secret_id: uuid.UUID | None,
) -> None:
    if managed_secret_id is None:
        return
    managed_secret = await managed_repository.get_managed_secret(session, managed_secret_id)
    if managed_secret is not None and managed_secret.status == "provisioning":
        managed_secret.status = "active"
        managed_secret.cleanup_error = ""
        await session.flush()


async def queue_managed_secret_cleanup(
    session: AsyncSession,
    managed_secret_ids: set[uuid.UUID],
) -> None:
    if not managed_secret_ids:
        return
    result = await session.execute(
        select(ManagedSecret).where(ManagedSecret.id.in_(managed_secret_ids)).with_for_update()
    )
    now = datetime.now(UTC)
    for managed_secret in result.scalars().all():
        managed_secret.status = "cleanup_pending"
        managed_secret.cleanup_available_at = now
        managed_secret.cleanup_worker_id = ""
        managed_secret.cleanup_lease_expires_at = None
        managed_secret.cleanup_error = ""
    await session.flush()


async def queue_managed_secret_cleanup_independently(
    managed_secret_id: uuid.UUID,
    *,
    session_factory=AsyncSessionLocal,
) -> None:
    async with session_factory() as lifecycle_session:
        await queue_managed_secret_cleanup(lifecycle_session, {managed_secret_id})
        await lifecycle_session.commit()


async def reconcile_managed_secret_after_request(
    session: AsyncSession,
    managed_secret_id: uuid.UUID,
) -> None:
    """Finalize committed handles or compensate a rolled-back request."""
    managed_secret = await managed_repository.get_managed_secret(session, managed_secret_id)
    if managed_secret is None or managed_secret.status != "provisioning":
        return
    result = await session.execute(
        select(SecretHandle.id).where(SecretHandle.managed_secret_id == managed_secret_id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        managed_secret.status = "active"
        managed_secret.cleanup_error = ""
    else:
        managed_secret.status = "cleanup_pending"
        managed_secret.cleanup_available_at = datetime.now(UTC)
    await session.flush()


async def owner_managed_secrets(
    session: AsyncSession,
    *,
    owner_type: str,
    owner_id: uuid.UUID,
) -> list[ManagedSecret]:
    return await managed_repository.list_owner_managed_secrets(
        session,
        owner_type=owner_type,
        owner_id=owner_id,
    )


async def delete_managed_secret_handles(
    session: AsyncSession,
    managed_secret_ids: set[uuid.UUID],
) -> None:
    handles = await managed_repository.list_managed_secret_handles(
        session,
        managed_secret_ids,
    )
    for handle in handles:
        await session.delete(handle)
    await session.flush()
