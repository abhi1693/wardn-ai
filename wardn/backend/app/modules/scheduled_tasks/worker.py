import asyncio
import logging
import socket
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from app.db.session import AsyncSessionLocal
from app.modules.scheduled_tasks import repository, service
from app.modules.scheduled_tasks.models import WorkspaceScheduledTaskRun

logger = logging.getLogger(__name__)


class ScheduledTaskLeaseLostError(Exception):
    pass


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def retry_delay_seconds(attempt: int, *, base_seconds: int, max_seconds: int) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def public_error_message(exc: BaseException, *, limit: int = 4000) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:limit]


def task_run_log_extra(run: WorkspaceScheduledTaskRun, *, worker_id: str) -> dict[str, str | int]:
    return {
        "scheduled_task_run_id": str(run.id),
        "scheduled_task_id": str(run.task_id),
        "organization_id": str(run.organization_id),
        "workspace_id": str(run.workspace_id),
        "agent_id": str(run.agent_id),
        "worker_id": worker_id,
        "attempt_count": run.attempt_count,
        "max_attempts": run.max_attempts,
        "trigger_source": run.trigger_source,
    }


async def heartbeat_run_once(
    *,
    session_factory,
    run_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
) -> None:
    async with session_factory() as session:
        renewed = await repository.heartbeat_run(
            session,
            run_id,
            worker_id=worker_id,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )
        if not renewed:
            await session.rollback()
            raise ScheduledTaskLeaseLostError("scheduled task run lease was lost")
        await session.commit()


async def heartbeat_run_loop(
    *,
    session_factory,
    run_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
    sleep=asyncio.sleep,
) -> None:
    while True:
        await sleep(heartbeat_seconds)
        await heartbeat_run_once(
            session_factory=session_factory,
            run_id=run_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )


async def run_with_heartbeat(
    operation,
    *,
    session_factory,
    run_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
):
    operation_task = asyncio.create_task(operation)
    heartbeat_task = asyncio.create_task(
        heartbeat_run_loop(
            session_factory=session_factory,
            run_id=run_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    )
    done, _pending = await asyncio.wait(
        {operation_task, heartbeat_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if operation_task in done:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        return await operation_task

    operation_task.cancel()
    with suppress(asyncio.CancelledError):
        await operation_task
    return await heartbeat_task


async def retry_or_fail_claimed_run(
    *,
    session_factory,
    run: WorkspaceScheduledTaskRun,
    worker_id: str,
    exc: BaseException,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    now = datetime.now(UTC)
    delay = retry_delay_seconds(
        run.attempt_count,
        base_seconds=retry_base_seconds,
        max_seconds=retry_max_seconds,
    )
    async with session_factory() as session:
        status = await repository.retry_or_fail_run(
            session,
            run.id,
            worker_id=worker_id,
            now=now,
            retry_at=now + timedelta(seconds=delay),
            error_message=public_error_message(exc),
        )
        if status is None:
            await session.rollback()
            raise ScheduledTaskLeaseLostError("scheduled task run lease was lost")
        await session.commit()


async def execute_task_run(
    run: WorkspaceScheduledTaskRun,
    *,
    worker_id: str,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    try:
        logger.info(
            "Starting scheduled task run.",
            extra=task_run_log_extra(run, worker_id=worker_id),
        )

        async def operation() -> None:
            async with session_factory() as session:
                claimed = await repository.get_owned_running_run(
                    session,
                    run.id,
                    worker_id=worker_id,
                )
                if claimed is None:
                    raise ScheduledTaskLeaseLostError("scheduled task run lease was lost")
                await service.execute_claimed_task_run(
                    session,
                    run=claimed,
                    worker_id=worker_id,
                    session_factory=session_factory,
                )
                await session.commit()

        await run_with_heartbeat(
            operation(),
            session_factory=session_factory,
            run_id=run.id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
        logger.info(
            "Completed scheduled task run.",
            extra=task_run_log_extra(run, worker_id=worker_id),
        )
    except asyncio.CancelledError:
        raise
    except ScheduledTaskLeaseLostError:
        logger.warning(
            "Lost scheduled task run lease.",
            extra=task_run_log_extra(run, worker_id=worker_id),
        )
    except Exception as exc:
        logger.exception(
            "Scheduled task run failed.",
            extra=task_run_log_extra(run, worker_id=worker_id),
        )
        await retry_or_fail_claimed_run(
            session_factory=session_factory,
            run=run,
            worker_id=worker_id,
            exc=exc,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )


async def run_scheduled_task_worker_once(
    *,
    worker_id: str,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> bool:
    now = datetime.now(UTC)
    async with session_factory() as session:
        recovered = await repository.recover_expired_leases(session, now=now)
        if recovered:
            logger.warning("Recovered %s expired scheduled task run leases.", recovered)
        enqueued = await service.enqueue_due_task_runs(session, now=now)
        if enqueued:
            logger.info("Enqueued %s due scheduled task runs.", enqueued)
        run = await repository.claim_next_run(
            session,
            worker_id=worker_id,
            now=datetime.now(UTC),
            lease_seconds=lease_seconds,
        )
        await session.commit()

    if run is None:
        return bool(enqueued or recovered)
    await execute_task_run(
        run,
        worker_id=worker_id,
        session_factory=session_factory,
        lease_seconds=lease_seconds,
        heartbeat_seconds=heartbeat_seconds,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    return True


async def run_scheduled_task_worker_loop(
    *,
    worker_id: str,
    poll_interval_seconds: float,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
    sleep=asyncio.sleep,
) -> None:
    while True:
        try:
            worked = await run_scheduled_task_worker_once(
                worker_id=worker_id,
                session_factory=session_factory,
                lease_seconds=lease_seconds,
                heartbeat_seconds=heartbeat_seconds,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled task worker iteration failed.")
            worked = False
        if not worked:
            await sleep(poll_interval_seconds)
