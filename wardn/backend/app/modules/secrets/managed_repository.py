import uuid
from datetime import datetime

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.secrets.models import ManagedSecret, SecretHandle, SecretStore


async def get_managed_secret(
    session: AsyncSession,
    managed_secret_id: uuid.UUID,
) -> ManagedSecret | None:
    return await session.get(ManagedSecret, managed_secret_id)


async def list_owner_managed_secrets(
    session: AsyncSession,
    *,
    owner_type: str,
    owner_id: uuid.UUID,
) -> list[ManagedSecret]:
    result = await session.execute(
        select(ManagedSecret).where(
            ManagedSecret.owner_type == owner_type,
            ManagedSecret.owner_id == owner_id,
        )
    )
    return list(result.scalars().all())


async def list_managed_secret_handles(
    session: AsyncSession,
    managed_secret_ids: set[uuid.UUID],
) -> list[SecretHandle]:
    if not managed_secret_ids:
        return []
    result = await session.execute(
        select(SecretHandle).where(SecretHandle.managed_secret_id.in_(managed_secret_ids))
    )
    return list(result.scalars().all())


async def activate_committed_provisioning(
    session: AsyncSession,
    *,
    stale_before: datetime,
) -> int:
    attached_handle = exists(
        select(SecretHandle.id).where(
            SecretHandle.managed_secret_id == ManagedSecret.id,
        )
    )
    result = await session.execute(
        update(ManagedSecret)
        .where(
            ManagedSecret.status == "provisioning",
            ManagedSecret.created_at <= stale_before,
            attached_handle,
        )
        .values(status="active", cleanup_error="")
    )
    return result.rowcount


async def recover_expired_cleanup_leases(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    result = await session.execute(
        update(ManagedSecret)
        .where(
            ManagedSecret.status == "cleaning",
            ManagedSecret.cleanup_lease_expires_at.is_not(None),
            ManagedSecret.cleanup_lease_expires_at <= now,
        )
        .values(
            status="cleanup_failed",
            cleanup_available_at=now,
            cleanup_worker_id="",
            cleanup_lease_expires_at=None,
            cleanup_error="The cleanup worker stopped renewing its lease",
        )
    )
    return result.rowcount


def claimable_cleanup_statement(*, now: datetime, stale_before: datetime):
    attached_handle = exists(
        select(SecretHandle.id).where(
            SecretHandle.managed_secret_id == ManagedSecret.id,
        )
    )
    return (
        select(ManagedSecret)
        .where(
            ManagedSecret.cleanup_available_at <= now,
            ManagedSecret.cleanup_attempt_count < ManagedSecret.cleanup_max_attempts,
            or_(
                ManagedSecret.status.in_(("cleanup_pending", "cleanup_failed")),
                (
                    (ManagedSecret.status == "provisioning")
                    & (ManagedSecret.created_at <= stale_before)
                    & ~attached_handle
                ),
            ),
        )
        .order_by(
            ManagedSecret.cleanup_available_at.asc(),
            ManagedSecret.created_at.asc(),
            ManagedSecret.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def claim_next_cleanup(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    stale_before: datetime,
    lease_expires_at: datetime,
) -> ManagedSecret | None:
    result = await session.execute(claimable_cleanup_statement(now=now, stale_before=stale_before))
    managed_secret = result.scalar_one_or_none()
    if managed_secret is None:
        return None
    managed_secret.status = "cleaning"
    managed_secret.cleanup_worker_id = worker_id
    managed_secret.cleanup_lease_expires_at = lease_expires_at
    managed_secret.cleanup_attempt_count += 1
    managed_secret.cleanup_error = ""
    await session.flush()
    return managed_secret


async def load_cleanup_target(
    session: AsyncSession,
    managed_secret_id: uuid.UUID,
    *,
    worker_id: str,
) -> tuple[ManagedSecret, SecretStore] | None:
    result = await session.execute(
        select(ManagedSecret, SecretStore)
        .join(SecretStore, SecretStore.id == ManagedSecret.store_id)
        .where(
            ManagedSecret.id == managed_secret_id,
            ManagedSecret.status == "cleaning",
            ManagedSecret.cleanup_worker_id == worker_id,
        )
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row is not None else None


async def complete_cleanup(
    session: AsyncSession,
    managed_secret_id: uuid.UUID,
    *,
    worker_id: str,
) -> bool:
    result = await session.execute(
        select(ManagedSecret)
        .where(
            ManagedSecret.id == managed_secret_id,
            ManagedSecret.status == "cleaning",
            ManagedSecret.cleanup_worker_id == worker_id,
        )
        .with_for_update()
    )
    managed_secret = result.scalar_one_or_none()
    if managed_secret is None:
        return False
    handles = await list_managed_secret_handles(session, {managed_secret.id})
    for handle in handles:
        await session.delete(handle)
    await session.flush()
    await session.delete(managed_secret)
    await session.flush()
    return True


async def retry_or_fail_cleanup(
    session: AsyncSession,
    managed_secret_id: uuid.UUID,
    *,
    worker_id: str,
    retry_at: datetime,
    error_message: str,
) -> bool:
    result = await session.execute(
        select(ManagedSecret)
        .where(
            ManagedSecret.id == managed_secret_id,
            ManagedSecret.status == "cleaning",
            ManagedSecret.cleanup_worker_id == worker_id,
        )
        .with_for_update()
    )
    managed_secret = result.scalar_one_or_none()
    if managed_secret is None:
        return False
    managed_secret.status = "cleanup_failed"
    managed_secret.cleanup_available_at = retry_at
    managed_secret.cleanup_worker_id = ""
    managed_secret.cleanup_lease_expires_at = None
    managed_secret.cleanup_error = error_message[:4000]
    await session.flush()
    return True
