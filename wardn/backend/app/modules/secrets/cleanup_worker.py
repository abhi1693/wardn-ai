import asyncio
import logging
import socket
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.db.session import AsyncSessionLocal
from app.modules.secrets import managed_repository
from app.modules.secrets.provider import SecretResolutionContext
from app.modules.secrets.providers.registry import get_secret_provider

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def retry_delay_seconds(attempt: int, *, base_seconds: int, max_seconds: int) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))


async def persist_cleanup_failure(
    managed_secret_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    exc: BaseException,
    session_factory,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    delay = retry_delay_seconds(
        attempt,
        base_seconds=retry_base_seconds,
        max_seconds=retry_max_seconds,
    )
    message = (str(exc).strip() or exc.__class__.__name__)[:4000]
    async with session_factory() as session:
        updated = await managed_repository.retry_or_fail_cleanup(
            session,
            managed_secret_id,
            worker_id=worker_id,
            retry_at=datetime.now(UTC) + timedelta(seconds=delay),
            error_message=message,
        )
        if updated:
            await session.commit()
        else:
            await session.rollback()
            logger.warning("Lost the cleanup lease for managed secret %s.", managed_secret_id)


async def execute_cleanup(
    managed_secret_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    session_factory=AsyncSessionLocal,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    try:
        async with session_factory() as session:
            target = await managed_repository.load_cleanup_target(
                session,
                managed_secret_id,
                worker_id=worker_id,
            )
            await session.commit()
        if target is None:
            logger.warning("Lost the cleanup lease for managed secret %s.", managed_secret_id)
            return
        managed_secret, store = target
        provider = get_secret_provider(store.provider)
        await provider.delete(
            store,
            managed_secret.external_ref,
            SecretResolutionContext(
                organization_id=str(managed_secret.organization_id),
                workspace_id=(
                    str(managed_secret.workspace_id) if managed_secret.workspace_id else None
                ),
                purpose=managed_secret.purpose,
            ),
        )
        async with session_factory() as session:
            completed = await managed_repository.complete_cleanup(
                session,
                managed_secret_id,
                worker_id=worker_id,
            )
            if completed:
                await session.commit()
                logger.info("Cleaned managed secret %s.", managed_secret_id)
            else:
                await session.rollback()
                logger.warning("Lost the cleanup lease for managed secret %s.", managed_secret_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Cleanup for managed secret %s failed.", managed_secret_id)
        await persist_cleanup_failure(
            managed_secret_id,
            worker_id=worker_id,
            attempt=attempt,
            exc=exc,
            session_factory=session_factory,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )


async def run_cleanup_worker_once(
    *,
    worker_id: str,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    provisioning_grace_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> bool:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=provisioning_grace_seconds)
    async with session_factory() as session:
        recovered = await managed_repository.recover_expired_cleanup_leases(session, now=now)
        activated = await managed_repository.activate_committed_provisioning(
            session,
            stale_before=stale_before,
        )
        managed_secret = await managed_repository.claim_next_cleanup(
            session,
            worker_id=worker_id,
            now=now,
            stale_before=stale_before,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        await session.commit()
    if recovered:
        logger.warning("Recovered %s expired managed-secret cleanup leases.", recovered)
    if activated:
        logger.info("Activated %s committed managed-secret provisioning records.", activated)
    if managed_secret is None:
        return False
    await execute_cleanup(
        managed_secret.id,
        worker_id=worker_id,
        attempt=managed_secret.cleanup_attempt_count,
        session_factory=session_factory,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    return True


async def run_cleanup_worker_loop(
    *,
    worker_id: str,
    poll_interval_seconds: float,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    provisioning_grace_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
    sleep: Sleep = asyncio.sleep,
) -> None:
    while True:
        try:
            worked = await run_cleanup_worker_once(
                worker_id=worker_id,
                session_factory=session_factory,
                lease_seconds=lease_seconds,
                provisioning_grace_seconds=provisioning_grace_seconds,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Managed-secret cleanup worker iteration failed.")
            worked = False
        if not worked:
            await sleep(poll_interval_seconds)
