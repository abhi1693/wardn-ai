import asyncio
import logging
import socket
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from app.db.session import AsyncSessionLocal
from app.modules.agents import approvals, repository
from app.modules.agents.models import AgentRunResumeJob
from app.modules.users import repository as users_repository

logger = logging.getLogger(__name__)


class AgentRunResumeLeaseLostError(Exception):
    pass


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def retry_delay_seconds(attempt: int, *, base_seconds: int, max_seconds: int) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def public_error_message(exc: BaseException, *, limit: int = 4000) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:limit]


def resume_job_log_extra(job: AgentRunResumeJob, *, worker_id: str) -> dict[str, str | int]:
    return {
        "agent_run_resume_job_id": str(job.id),
        "agent_run_id": str(job.agent_run_id),
        "approval_id": str(job.approval_id),
        "organization_id": str(job.organization_id),
        "workspace_id": str(job.workspace_id),
        "agent_id": str(job.agent_id),
        "user_id": str(job.user_id or ""),
        "worker_id": worker_id,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
    }


async def heartbeat_resume_job_once(
    *,
    session_factory,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
) -> None:
    async with session_factory() as session:
        renewed = await repository.heartbeat_agent_run_resume_job(
            session,
            job_id,
            worker_id=worker_id,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )
        if not renewed:
            await session.rollback()
            raise AgentRunResumeLeaseLostError("agent run resume job lease was lost")
        await session.commit()


async def heartbeat_resume_job_loop(
    *,
    session_factory,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
    sleep=asyncio.sleep,
) -> None:
    while True:
        await sleep(heartbeat_seconds)
        await heartbeat_resume_job_once(
            session_factory=session_factory,
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )


async def run_with_heartbeat(
    operation,
    *,
    session_factory,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
):
    operation_task = asyncio.create_task(operation)
    heartbeat_task = asyncio.create_task(
        heartbeat_resume_job_loop(
            session_factory=session_factory,
            job_id=job_id,
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


async def fail_agent_run_for_resume_job(
    *,
    session_factory,
    job: AgentRunResumeJob,
    worker_id: str,
    error_message: str,
) -> None:
    async with session_factory() as session:
        agent_run = await repository.get_agent_run(
            session,
            organization_id=job.organization_id,
            workspace_id=job.workspace_id,
            agent_run_id=job.agent_run_id,
        )
        if agent_run is not None:
            await repository.append_agent_run_step(
                session,
                agent_run_id=agent_run.id,
                step_type="approval_resume_failed",
                status="failed",
                title="Approval resume failed",
                payload={
                    "resumeJobId": str(job.id),
                    "approvalId": str(job.approval_id),
                    "error": error_message,
                },
            )
            await repository.finish_agent_run(
                session,
                agent_run,
                status="failed",
                error=error_message,
            )
        await session.commit()
    logger.error(
        "Agent run resume job failed permanently.",
        extra={**resume_job_log_extra(job, worker_id=worker_id), "error": error_message},
    )


async def retry_or_fail_claimed_resume_job(
    *,
    session_factory,
    job: AgentRunResumeJob,
    worker_id: str,
    exc: BaseException,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    now = datetime.now(UTC)
    delay = retry_delay_seconds(
        job.attempt_count,
        base_seconds=retry_base_seconds,
        max_seconds=retry_max_seconds,
    )
    error_message = public_error_message(exc)
    async with session_factory() as session:
        status = await repository.retry_or_fail_agent_run_resume_job(
            session,
            job.id,
            worker_id=worker_id,
            now=now,
            retry_at=now + timedelta(seconds=delay),
            error_message=error_message,
        )
        if status is None:
            await session.rollback()
            raise AgentRunResumeLeaseLostError("agent run resume job lease was lost")
        await session.commit()
    if status == "failed":
        await fail_agent_run_for_resume_job(
            session_factory=session_factory,
            job=job,
            worker_id=worker_id,
            error_message=error_message,
        )


async def execute_agent_run_resume_job(
    job: AgentRunResumeJob,
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
            "Starting agent run resume job.",
            extra=resume_job_log_extra(job, worker_id=worker_id),
        )

        async def operation() -> None:
            async with session_factory() as session:
                claimed = await repository.get_owned_agent_run_resume_job(
                    session,
                    job.id,
                    worker_id=worker_id,
                )
                if claimed is None:
                    raise AgentRunResumeLeaseLostError("agent run resume job lease was lost")
                user = (
                    await users_repository.get_user_by_id(session, claimed.user_id)
                    if claimed.user_id is not None
                    else None
                )
                if user is None or not user.is_active:
                    raise RuntimeError("approval reviewer is no longer an active user")
                await repository.append_agent_run_step(
                    session,
                    agent_run_id=claimed.agent_run_id,
                    step_type="approval_resume_running",
                    status="running",
                    title="Approval resume",
                    payload={
                        "resumeJobId": str(claimed.id),
                        "approvalId": str(claimed.approval_id),
                    },
                )
                await session.commit()

            async with session_factory() as session:
                await approvals.complete_agent_tool_approval(
                    session,
                    user,
                    job.organization_id,
                    job.workspace_id,
                    job.agent_id,
                    job.approval_id,
                    checkpoint_after_execution=session.commit,
                    session_factory=session_factory,
                )

            async with session_factory() as session:
                completed = await repository.complete_agent_run_resume_job(
                    session,
                    job.id,
                    worker_id=worker_id,
                    now=datetime.now(UTC),
                )
                if not completed:
                    raise AgentRunResumeLeaseLostError("agent run resume job lease was lost")
                await session.commit()

        await run_with_heartbeat(
            operation(),
            session_factory=session_factory,
            job_id=job.id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
        logger.info(
            "Completed agent run resume job.",
            extra=resume_job_log_extra(job, worker_id=worker_id),
        )
    except asyncio.CancelledError:
        raise
    except AgentRunResumeLeaseLostError:
        logger.warning(
            "Lost agent run resume job lease.",
            extra=resume_job_log_extra(job, worker_id=worker_id),
        )
    except Exception as exc:
        logger.exception(
            "Agent run resume job failed.",
            extra=resume_job_log_extra(job, worker_id=worker_id),
        )
        await retry_or_fail_claimed_resume_job(
            session_factory=session_factory,
            job=job,
            worker_id=worker_id,
            exc=exc,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )


async def run_agent_run_resume_worker_once(
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
        recovered = await repository.recover_expired_agent_run_resume_jobs(
            session,
            now=now,
        )
        if recovered:
            logger.warning("Recovered %s expired agent run resume job leases.", recovered)
        stale_enqueued = await repository.enqueue_stale_agent_run_resume_jobs(
            session,
            now=now,
            stale_before=now - timedelta(seconds=lease_seconds),
        )
        if stale_enqueued:
            logger.warning(
                "Queued %s stale agent run approval resume jobs.",
                stale_enqueued,
            )
        orphaned_failed = await repository.fail_stale_orphaned_agent_runs(
            session,
            now=now,
            stale_before=now - timedelta(seconds=lease_seconds),
        )
        if orphaned_failed:
            logger.warning("Failed %s stale orphaned agent runs.", orphaned_failed)
        job = await repository.claim_next_agent_run_resume_job(
            session,
            worker_id=worker_id,
            now=datetime.now(UTC),
            lease_seconds=lease_seconds,
        )
        await session.commit()

    if job is None:
        return bool(recovered or stale_enqueued or orphaned_failed)
    await execute_agent_run_resume_job(
        job,
        worker_id=worker_id,
        session_factory=session_factory,
        lease_seconds=lease_seconds,
        heartbeat_seconds=heartbeat_seconds,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    return True


async def run_agent_run_resume_worker_loop(
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
            worked = await run_agent_run_resume_worker_once(
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
            logger.exception("Agent run resume worker iteration failed.")
            worked = False
        if not worked:
            await sleep(poll_interval_seconds)
