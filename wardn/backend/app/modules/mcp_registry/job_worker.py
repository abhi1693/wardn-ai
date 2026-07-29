import asyncio
import logging
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.session import AsyncSessionLocal
from app.modules.mcp_registry import job_repository
from app.modules.mcp_registry.models import MCPOperationJob

logger = logging.getLogger(__name__)


class MCPJobExecutionError(Exception):
    def __init__(self, message: str, *, code: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class MCPJobLeaseLostError(MCPJobExecutionError):
    def __init__(self, message: str = "MCP operation job lease was lost") -> None:
        super().__init__(message, code="job_lease_lost", retryable=True)


class MCPJobCleanupError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


JobExecutor = Callable[[MCPOperationJob, "JobProgressReporter"], Awaitable[dict[str, Any]]]
CleanupExecutor = Callable[[MCPOperationJob, dict[str, Any]], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class MCPJobHandlers:
    executors: Mapping[str, JobExecutor]
    cleanup_executors: Mapping[str, CleanupExecutor]


def job_log_extra(job: MCPOperationJob, *, worker_id: str) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "mcp_job_id": str(job.id),
        "mcp_operation": job.operation,
        "mcp_resource_key": job.resource_key,
        "mcp_job_status": job.status,
        "organization_id": str(job.organization_id),
        "workspace_id": str(job.workspace_id) if job.workspace_id else None,
        "worker_id": worker_id,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
    }
    request_payload = job.request_payload if isinstance(job.request_payload, dict) else {}
    if isinstance(request_payload.get("serverName"), str):
        extra["mcp_server_name"] = request_payload["serverName"]
    desired_state = request_payload.get("desiredState")
    if isinstance(desired_state, dict):
        if isinstance(desired_state.get("version"), str):
            extra["mcp_server_version"] = desired_state["version"]
        if isinstance(desired_state.get("configName"), str):
            extra["mcp_config_name"] = desired_state["configName"]
        if isinstance(desired_state.get("installTarget"), str):
            extra["mcp_install_target"] = desired_state["installTarget"]
    targets = request_payload.get("targets")
    if isinstance(targets, list):
        extra["mcp_update_target_count"] = len(targets)
        extra["mcp_update_server_count"] = len(
            {
                target.get("serverName")
                for target in targets
                if isinstance(target, dict) and isinstance(target.get("serverName"), str)
            }
        )
    return extra


def cleanup_log_extra(job: MCPOperationJob, *, worker_id: str) -> dict[str, Any]:
    extra = job_log_extra(job, worker_id=worker_id)
    extra.update(
        {
            "cleanup_status": job.cleanup_status,
            "cleanup_attempt_count": job.cleanup_attempt_count,
            "cleanup_max_attempts": job.cleanup_max_attempts,
        }
    )
    return extra


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def retry_delay_seconds(attempt: int, *, base_seconds: int, max_seconds: int) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def public_error_message(exc: BaseException, *, limit: int = 4000) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:limit]


class JobProgressReporter:
    def __init__(
        self,
        *,
        session_factory,
        job_id: uuid.UUID,
        worker_id: str,
        log_extra: dict[str, Any] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.job_id = job_id
        self.worker_id = worker_id
        self.log_extra = dict(log_extra or {})

    async def update(
        self,
        current: int,
        total: int,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if current < 0 or total < 1 or current > total:
            raise ValueError("job progress must satisfy 0 <= current <= total")
        async with self.session_factory() as session:
            updated = await job_repository.record_job_progress(
                session,
                self.job_id,
                worker_id=self.worker_id,
                current=current,
                total=total,
                message=message,
                details=details,
            )
            if not updated:
                await session.rollback()
                raise MCPJobLeaseLostError()
            await session.commit()
        progress_extra = dict(self.log_extra)
        progress_extra.update(
            {
                "mcp_job_progress_current": current,
                "mcp_job_progress_total": total,
                "mcp_job_progress_message": message,
            }
        )
        if details:
            progress_extra["mcp_job_progress_details"] = details
        logger.info("MCP operation job progress: %s", message, extra=progress_extra)

    async def register_cleanup(self, payload: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            updated = await job_repository.register_job_cleanup(
                session,
                self.job_id,
                worker_id=self.worker_id,
                payload=payload,
            )
            if not updated:
                await session.rollback()
                raise MCPJobLeaseLostError()
            await session.commit()


async def heartbeat_job_once(
    *,
    session_factory,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    cleanup: bool,
) -> None:
    async with session_factory() as session:
        lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        heartbeat = (
            job_repository.heartbeat_cleanup
            if cleanup
            else job_repository.heartbeat_job
        )
        renewed = await heartbeat(
            session,
            job_id,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
        )
        if not renewed:
            await session.rollback()
            raise MCPJobLeaseLostError()
        await session.commit()


async def heartbeat_job_loop(
    *,
    session_factory,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
    cleanup: bool,
    sleep: Sleep = asyncio.sleep,
) -> None:
    while True:
        await sleep(heartbeat_seconds)
        await heartbeat_job_once(
            session_factory=session_factory,
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            cleanup=cleanup,
        )


async def run_with_heartbeat(
    operation: Awaitable[Any],
    *,
    session_factory,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    heartbeat_seconds: int,
    cleanup: bool = False,
) -> Any:
    operation_task = asyncio.create_task(operation)
    heartbeat_task = asyncio.create_task(
        heartbeat_job_loop(
            session_factory=session_factory,
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
            cleanup=cleanup,
        )
    )
    done, _ = await asyncio.wait(
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


async def persist_job_success(
    *,
    session_factory,
    job: MCPOperationJob,
    worker_id: str,
    result: dict[str, Any],
) -> None:
    async with session_factory() as session:
        completed = await job_repository.complete_job(
            session,
            job.id,
            worker_id=worker_id,
            now=datetime.now(UTC),
            result=result,
        )
        if not completed:
            await session.rollback()
            raise MCPJobLeaseLostError()
        await session.commit()


async def persist_job_failure(
    *,
    session_factory,
    job: MCPOperationJob,
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
    if isinstance(exc, MCPJobExecutionError):
        error_code = exc.code
        retryable = exc.retryable
    else:
        error_code = "operation_failed"
        retryable = True
    async with session_factory() as session:
        status = await job_repository.retry_or_fail_job(
            session,
            job.id,
            worker_id=worker_id,
            now=now,
            retry_at=now + timedelta(seconds=delay),
            error_code=error_code,
            error_message=public_error_message(exc),
            retryable=retryable,
        )
        if status is None:
            await session.rollback()
            raise MCPJobLeaseLostError()
        await session.commit()


async def execute_job(
    job: MCPOperationJob,
    *,
    worker_id: str,
    handlers: MCPJobHandlers,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    executor = handlers.executors.get(job.operation)
    started_at = time.monotonic()
    reporter = JobProgressReporter(
        session_factory=session_factory,
        job_id=job.id,
        worker_id=worker_id,
        log_extra=job_log_extra(job, worker_id=worker_id),
    )
    try:
        logger.info(
            "Starting MCP operation job.",
            extra=job_log_extra(job, worker_id=worker_id),
        )
        if executor is None:
            raise MCPJobExecutionError(
                f"Unsupported MCP operation: {job.operation}",
                code="unsupported_operation",
                retryable=False,
            )
        result = await run_with_heartbeat(
            executor(job, reporter),
            session_factory=session_factory,
            job_id=job.id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    except asyncio.CancelledError:
        raise
    except MCPJobLeaseLostError:
        logger.warning(
            "Lost MCP operation job lease.",
            extra=job_log_extra(job, worker_id=worker_id),
        )
        return
    except Exception as exc:
        failure_extra = job_log_extra(job, worker_id=worker_id)
        failure_extra.update(
            {
                "error_type": exc.__class__.__name__,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            }
        )
        logger.exception("MCP operation job failed.", extra=failure_extra)
        try:
            await persist_job_failure(
                session_factory=session_factory,
                job=job,
                worker_id=worker_id,
                exc=exc,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
        except MCPJobLeaseLostError:
            logger.warning(
                "Could not persist MCP operation job failure after lease loss.",
                extra=job_log_extra(job, worker_id=worker_id),
            )
        return

    try:
        await persist_job_success(
            session_factory=session_factory,
            job=job,
            worker_id=worker_id,
            result=result,
        )
    except MCPJobLeaseLostError:
        logger.warning(
            "Could not persist MCP operation job success after lease loss.",
            extra=job_log_extra(job, worker_id=worker_id),
        )
        return
    success_extra = job_log_extra(job, worker_id=worker_id)
    success_extra["duration_ms"] = int((time.monotonic() - started_at) * 1000)
    logger.info("Completed MCP operation job.", extra=success_extra)


async def persist_cleanup_failure(
    *,
    session_factory,
    job: MCPOperationJob,
    worker_id: str,
    exc: BaseException,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    delay = retry_delay_seconds(
        job.cleanup_attempt_count,
        base_seconds=retry_base_seconds,
        max_seconds=retry_max_seconds,
    )
    retryable = not isinstance(exc, MCPJobCleanupError) or exc.retryable
    async with session_factory() as session:
        status = await job_repository.retry_or_fail_cleanup(
            session,
            job.id,
            worker_id=worker_id,
            retry_at=datetime.now(UTC) + timedelta(seconds=delay),
            error_message=public_error_message(exc),
            retryable=retryable,
        )
        if status is None:
            await session.rollback()
            raise MCPJobLeaseLostError()
        await session.commit()


async def execute_cleanup(
    job: MCPOperationJob,
    *,
    worker_id: str,
    handlers: MCPJobHandlers,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    executor = handlers.cleanup_executors.get(job.operation)
    started_at = time.monotonic()
    try:
        logger.info(
            "Starting MCP operation job cleanup.",
            extra=cleanup_log_extra(job, worker_id=worker_id),
        )
        if executor is None:
            raise MCPJobCleanupError(
                f"Unsupported cleanup for MCP operation: {job.operation}",
                retryable=False,
            )
        await run_with_heartbeat(
            executor(job, job.cleanup_payload),
            session_factory=session_factory,
            job_id=job.id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
            cleanup=True,
        )
    except asyncio.CancelledError:
        raise
    except MCPJobLeaseLostError:
        logger.warning(
            "Lost MCP operation job cleanup lease.",
            extra=cleanup_log_extra(job, worker_id=worker_id),
        )
        return
    except Exception as exc:
        failure_extra = cleanup_log_extra(job, worker_id=worker_id)
        failure_extra.update(
            {
                "error_type": exc.__class__.__name__,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            }
        )
        logger.exception("MCP operation job cleanup failed.", extra=failure_extra)
        try:
            await persist_cleanup_failure(
                session_factory=session_factory,
                job=job,
                worker_id=worker_id,
                exc=exc,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
        except MCPJobLeaseLostError:
            logger.warning(
                "Could not persist MCP operation cleanup failure after lease loss.",
                extra=cleanup_log_extra(job, worker_id=worker_id),
            )
        return

    async with session_factory() as session:
        completed = await job_repository.complete_cleanup(
            session,
            job.id,
            worker_id=worker_id,
        )
        if not completed:
            await session.rollback()
            logger.warning(
                "Could not persist MCP operation cleanup success after lease loss.",
                extra=cleanup_log_extra(job, worker_id=worker_id),
            )
            return
        await session.commit()
    success_extra = cleanup_log_extra(job, worker_id=worker_id)
    success_extra["duration_ms"] = int((time.monotonic() - started_at) * 1000)
    logger.info("Completed MCP operation job cleanup.", extra=success_extra)


async def run_job_worker_once(
    *,
    worker_id: str,
    handlers: MCPJobHandlers,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> bool:
    async with session_factory() as session:
        recovered = await job_repository.recover_expired_leases(
            session,
            now=datetime.now(UTC),
        )
        if recovered:
            logger.warning("Recovered %s expired MCP operation job leases.", recovered)
        cleanup = await job_repository.claim_next_cleanup(
            session,
            worker_id=worker_id,
            now=datetime.now(UTC),
            lease_seconds=lease_seconds,
        )
        job = None
        if cleanup is None:
            job = await job_repository.claim_next_job(
                session,
                worker_id=worker_id,
                now=datetime.now(UTC),
                lease_seconds=lease_seconds,
            )
        await session.commit()

    if cleanup is not None:
        logger.info(
            "Claimed MCP operation job cleanup.",
            extra=cleanup_log_extra(cleanup, worker_id=worker_id),
        )
        await execute_cleanup(
            cleanup,
            worker_id=worker_id,
            handlers=handlers,
            session_factory=session_factory,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        return True
    if job is not None:
        logger.info(
            "Claimed MCP operation job.",
            extra=job_log_extra(job, worker_id=worker_id),
        )
        await execute_job(
            job,
            worker_id=worker_id,
            handlers=handlers,
            session_factory=session_factory,
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        return True
    return False


async def run_job_worker_loop(
    *,
    worker_id: str,
    handlers: MCPJobHandlers,
    poll_interval_seconds: float,
    session_factory=AsyncSessionLocal,
    lease_seconds: int,
    heartbeat_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
    sleep: Sleep = asyncio.sleep,
) -> None:
    while True:
        try:
            worked = await run_job_worker_once(
                worker_id=worker_id,
                handlers=handlers,
                session_factory=session_factory,
                lease_seconds=lease_seconds,
                heartbeat_seconds=heartbeat_seconds,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP operation worker iteration failed.")
            worked = False
        if not worked:
            await sleep(poll_interval_seconds)
