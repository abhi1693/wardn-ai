import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.mcp_registry.models import MCPOperationJob, MCPOperationJobEvent


def add_job_event(
    session: AsyncSession,
    job: MCPOperationJob,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    progress_current: int | None = None,
    progress_total: int | None = None,
    details: dict[str, Any] | None = None,
) -> MCPOperationJobEvent:
    event = MCPOperationJobEvent(
        job_id=job.id,
        event_type=event_type,
        level=level,
        message=message,
        progress_current=progress_current,
        progress_total=progress_total,
        details=details or {},
    )
    session.add(event)
    return event


async def get_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> MCPOperationJob | None:
    statement = select(MCPOperationJob).where(
        MCPOperationJob.id == job_id,
        MCPOperationJob.organization_id == organization_id,
    )
    if workspace_id is None:
        statement = statement.where(MCPOperationJob.workspace_id.is_(None))
    else:
        statement = statement.where(MCPOperationJob.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_active_job_by_deduplication_key(
    session: AsyncSession,
    deduplication_key: str,
) -> MCPOperationJob | None:
    result = await session.execute(
        select(MCPOperationJob).where(
            MCPOperationJob.deduplication_key == deduplication_key,
            MCPOperationJob.status.in_(("queued", "running")),
        )
    )
    return result.scalar_one_or_none()


async def list_job_events(
    session: AsyncSession,
    job_id: uuid.UUID,
) -> list[MCPOperationJobEvent]:
    result = await session.execute(
        select(MCPOperationJobEvent)
        .where(MCPOperationJobEvent.job_id == job_id)
        .order_by(MCPOperationJobEvent.created_at.asc(), MCPOperationJobEvent.id.asc())
    )
    return list(result.scalars().all())


def claimable_job_statement(now: datetime):
    candidate = aliased(MCPOperationJob)
    blocker = aliased(MCPOperationJob)
    earlier_active_job = exists(
        select(blocker.id).where(
            blocker.resource_key == candidate.resource_key,
            blocker.status.in_(("queued", "running")),
            or_(
                blocker.created_at < candidate.created_at,
                and_(
                    blocker.created_at == candidate.created_at,
                    blocker.id < candidate.id,
                ),
            ),
        )
    ).correlate(candidate)
    return (
        select(candidate)
        .where(
            candidate.status == "queued",
            candidate.available_at <= now,
            ~earlier_active_job,
        )
        .order_by(candidate.available_at.asc(), candidate.created_at.asc(), candidate.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def claim_next_job(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> MCPOperationJob | None:
    result = await session.execute(claimable_job_statement(now))
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.worker_id = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.error_code = ""
    job.error_message = ""
    add_job_event(
        session,
        job,
        event_type="started",
        message=f"Attempt {job.attempt_count} started",
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        details={"attempt": job.attempt_count, "workerId": worker_id},
    )
    await session.flush()
    return job


async def claim_next_cleanup(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> MCPOperationJob | None:
    result = await session.execute(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.status.in_(("succeeded", "failed")),
            MCPOperationJob.cleanup_status == "pending",
            MCPOperationJob.cleanup_available_at <= now,
        )
        .order_by(
            MCPOperationJob.cleanup_available_at.asc(),
            MCPOperationJob.created_at.asc(),
            MCPOperationJob.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.cleanup_status = "running"
    job.cleanup_worker_id = worker_id
    job.cleanup_lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.cleanup_attempt_count += 1
    job.cleanup_error = ""
    add_job_event(
        session,
        job,
        event_type="cleanup_started",
        message=f"Cleanup attempt {job.cleanup_attempt_count} started",
        details={"attempt": job.cleanup_attempt_count, "workerId": worker_id},
    )
    await session.flush()
    return job


async def heartbeat_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    lease_expires_at: datetime,
) -> bool:
    result = await session.execute(
        update(MCPOperationJob)
        .where(
            MCPOperationJob.id == job_id,
            MCPOperationJob.status == "running",
            MCPOperationJob.worker_id == worker_id,
        )
        .values(lease_expires_at=lease_expires_at)
    )
    return result.rowcount == 1


async def record_job_progress(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    current: int,
    total: int,
    message: str,
    details: dict[str, Any] | None = None,
) -> bool:
    result = await session.execute(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.id == job_id,
            MCPOperationJob.status == "running",
            MCPOperationJob.worker_id == worker_id,
        )
        .with_for_update()
    )
    job = result.scalar_one_or_none()
    if job is None:
        return False
    job.progress_current = current
    job.progress_total = total
    job.progress_message = message
    add_job_event(
        session,
        job,
        event_type="progress",
        message=message,
        progress_current=current,
        progress_total=total,
        details=details,
    )
    return True


async def register_job_cleanup(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    payload: dict[str, Any],
) -> bool:
    result = await session.execute(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.id == job_id,
            MCPOperationJob.status == "running",
            MCPOperationJob.worker_id == worker_id,
        )
        .with_for_update()
    )
    job = result.scalar_one_or_none()
    if job is None:
        return False
    job.cleanup_payload = payload
    job.cleanup_status = "pending" if payload else "not_required"
    job.cleanup_available_at = None
    add_job_event(
        session,
        job,
        event_type="cleanup_registered",
        message="Retryable cleanup registered" if payload else "Cleanup cleared",
    )
    return True


async def get_owned_running_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
) -> MCPOperationJob | None:
    result = await session.execute(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.id == job_id,
            MCPOperationJob.status == "running",
            MCPOperationJob.worker_id == worker_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def complete_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    now: datetime,
    result: dict[str, Any],
) -> bool:
    job = await get_owned_running_job(session, job_id, worker_id=worker_id)
    if job is None:
        return False
    job.status = "succeeded"
    job.result = result
    job.progress_current = job.progress_total
    job.progress_message = "Completed"
    job.completed_at = now
    job.worker_id = ""
    job.lease_expires_at = None
    if job.cleanup_payload:
        job.cleanup_status = "pending"
        job.cleanup_available_at = now
    else:
        job.cleanup_status = "not_required"
        job.cleanup_available_at = None
    add_job_event(
        session,
        job,
        event_type="succeeded",
        message="Operation completed",
        progress_current=job.progress_current,
        progress_total=job.progress_total,
    )
    return True


async def retry_or_fail_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    now: datetime,
    retry_at: datetime,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> str | None:
    job = await get_owned_running_job(session, job_id, worker_id=worker_id)
    if job is None:
        return None
    should_retry = retryable and job.attempt_count < job.max_attempts
    job.error_code = error_code
    job.error_message = error_message
    job.worker_id = ""
    job.lease_expires_at = None
    if should_retry:
        job.status = "queued"
        job.available_at = retry_at
        job.progress_message = "Retry scheduled"
        event_type = "retry_scheduled"
        message = f"Attempt failed; retry scheduled for {retry_at.isoformat()}"
    else:
        job.status = "failed"
        job.completed_at = now
        job.progress_message = "Failed"
        if job.cleanup_payload:
            job.cleanup_status = "pending"
            job.cleanup_available_at = now
        event_type = "failed"
        message = "Operation failed"
    add_job_event(
        session,
        job,
        event_type=event_type,
        level="warning" if should_retry else "error",
        message=message,
        details={"errorCode": error_code, "errorMessage": error_message},
    )
    return job.status


async def heartbeat_cleanup(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    lease_expires_at: datetime,
) -> bool:
    result = await session.execute(
        update(MCPOperationJob)
        .where(
            MCPOperationJob.id == job_id,
            MCPOperationJob.cleanup_status == "running",
            MCPOperationJob.cleanup_worker_id == worker_id,
        )
        .values(cleanup_lease_expires_at=lease_expires_at)
    )
    return result.rowcount == 1


async def get_owned_cleanup_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
) -> MCPOperationJob | None:
    result = await session.execute(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.id == job_id,
            MCPOperationJob.cleanup_status == "running",
            MCPOperationJob.cleanup_worker_id == worker_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def complete_cleanup(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
) -> bool:
    job = await get_owned_cleanup_job(session, job_id, worker_id=worker_id)
    if job is None:
        return False
    job.cleanup_status = "succeeded"
    job.cleanup_payload = {}
    job.cleanup_available_at = None
    job.cleanup_lease_expires_at = None
    job.cleanup_worker_id = ""
    job.cleanup_error = ""
    add_job_event(
        session,
        job,
        event_type="cleanup_succeeded",
        message="Cleanup completed",
    )
    return True


async def retry_or_fail_cleanup(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    retry_at: datetime,
    error_message: str,
    retryable: bool,
) -> str | None:
    job = await get_owned_cleanup_job(session, job_id, worker_id=worker_id)
    if job is None:
        return None
    should_retry = retryable and job.cleanup_attempt_count < job.cleanup_max_attempts
    job.cleanup_status = "pending" if should_retry else "failed"
    job.cleanup_available_at = retry_at if should_retry else None
    job.cleanup_lease_expires_at = None
    job.cleanup_worker_id = ""
    job.cleanup_error = error_message
    add_job_event(
        session,
        job,
        event_type="cleanup_retry_scheduled" if should_retry else "cleanup_failed",
        level="warning" if should_retry else "error",
        message="Cleanup retry scheduled" if should_retry else "Cleanup failed",
        details={"errorMessage": error_message},
    )
    return job.cleanup_status


async def recover_expired_leases(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> int:
    recovered = 0
    result = await session.execute(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.status == "running",
            MCPOperationJob.lease_expires_at <= now,
        )
        .order_by(MCPOperationJob.lease_expires_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    for job in result.scalars().all():
        retryable = job.attempt_count < job.max_attempts
        job.status = "queued" if retryable else "failed"
        job.available_at = now
        job.completed_at = None if retryable else now
        job.worker_id = ""
        job.lease_expires_at = None
        job.error_code = "worker_lease_expired"
        job.error_message = "The worker stopped renewing its lease"
        job.progress_message = "Retry scheduled" if retryable else "Failed"
        if not retryable and job.cleanup_payload:
            job.cleanup_status = "pending"
            job.cleanup_available_at = now
        add_job_event(
            session,
            job,
            event_type="lease_expired",
            level="warning" if retryable else "error",
            message=(
                "Worker lease expired; operation requeued"
                if retryable
                else "Worker lease expired; retry limit reached"
            ),
        )
        recovered += 1

    remaining = max(0, limit - recovered)
    if remaining:
        cleanup_result = await session.execute(
            select(MCPOperationJob)
            .where(
                MCPOperationJob.cleanup_status == "running",
                MCPOperationJob.cleanup_lease_expires_at <= now,
            )
            .order_by(MCPOperationJob.cleanup_lease_expires_at.asc())
            .limit(remaining)
            .with_for_update(skip_locked=True)
        )
        for job in cleanup_result.scalars().all():
            retryable = job.cleanup_attempt_count < job.cleanup_max_attempts
            job.cleanup_status = "pending" if retryable else "failed"
            job.cleanup_available_at = now if retryable else None
            job.cleanup_worker_id = ""
            job.cleanup_lease_expires_at = None
            job.cleanup_error = "The cleanup worker stopped renewing its lease"
            add_job_event(
                session,
                job,
                event_type="cleanup_lease_expired",
                level="warning" if retryable else "error",
                message=(
                    "Cleanup lease expired; cleanup requeued"
                    if retryable
                    else "Cleanup lease expired; retry limit reached"
                ),
            )
            recovered += 1
    return recovered
