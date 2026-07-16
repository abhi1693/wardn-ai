import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry import job_repository
from app.modules.mcp_registry.exceptions import MCPOperationJobNotFoundError
from app.modules.mcp_registry.models import MCPOperationJob, MCPOperationJobEvent
from app.modules.mcp_registry.schemas import MCPOperationJobEventRead, MCPOperationJobRead


def operation_deduplication_key(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    operation: str,
    resource_key: str,
    request_payload: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "organizationId": str(organization_id),
            "workspaceId": str(workspace_id) if workspace_id else None,
            "operation": operation,
            "resourceKey": resource_key,
            "request": request_payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def enqueue_operation_job(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    requested_by_id: uuid.UUID | None,
    operation: str,
    resource_key: str,
    request_payload: dict[str, Any],
    progress_total: int,
    max_attempts: int = 3,
    cleanup_max_attempts: int = 5,
    deduplication_key: str | None = None,
) -> MCPOperationJobRead:
    if not operation or len(operation) > 50:
        raise ValueError("MCP operation name must contain at most 50 characters")
    if not resource_key or len(resource_key) > 512:
        raise ValueError("MCP operation resource key must contain at most 512 characters")
    if progress_total < 1:
        raise ValueError("MCP operation progress total must be greater than 0")
    if max_attempts < 1 or cleanup_max_attempts < 1:
        raise ValueError("MCP operation retry limits must be greater than 0")

    deduplication_key = deduplication_key or operation_deduplication_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        operation=operation,
        resource_key=resource_key,
        request_payload=request_payload,
    )
    if len(deduplication_key) != 64:
        raise ValueError("MCP operation deduplication key must be a SHA-256 digest")
    existing = await job_repository.get_active_job_by_deduplication_key(
        session,
        deduplication_key,
    )
    if existing is not None:
        return job_response(existing, await job_repository.list_job_events(session, existing.id))

    job = MCPOperationJob(
        organization_id=organization_id,
        workspace_id=workspace_id,
        requested_by_id=requested_by_id,
        operation=operation,
        resource_key=resource_key,
        deduplication_key=deduplication_key,
        status="queued",
        request_payload=request_payload,
        result={},
        progress_current=0,
        progress_total=progress_total,
        progress_message="Queued",
        attempt_count=0,
        max_attempts=max_attempts,
        worker_id="",
        error_code="",
        error_message="",
        cleanup_status="not_required",
        cleanup_payload={},
        cleanup_attempt_count=0,
        cleanup_max_attempts=cleanup_max_attempts,
        cleanup_worker_id="",
        cleanup_error="",
    )
    try:
        async with session.begin_nested():
            session.add(job)
            await session.flush()
            job_repository.add_job_event(
                session,
                job,
                event_type="queued",
                message="Operation queued",
                progress_current=0,
                progress_total=progress_total,
            )
            await session.flush()
    except IntegrityError:
        existing = await job_repository.get_active_job_by_deduplication_key(
            session,
            deduplication_key,
        )
        if existing is None:
            raise
        return job_response(existing, await job_repository.list_job_events(session, existing.id))

    events = await job_repository.list_job_events(session, job.id)
    return job_response(job, events)


def job_event_response(event: MCPOperationJobEvent) -> MCPOperationJobEventRead:
    return MCPOperationJobEventRead(
        id=event.id,
        eventType=event.event_type,
        level=event.level,
        message=event.message,
        progressCurrent=event.progress_current,
        progressTotal=event.progress_total,
        details=event.details or {},
        createdAt=event.created_at,
    )


def job_response(
    job: MCPOperationJob,
    events: list[MCPOperationJobEvent],
) -> MCPOperationJobRead:
    return MCPOperationJobRead(
        jobId=job.id,
        organizationId=job.organization_id,
        workspaceId=job.workspace_id,
        operation=job.operation,
        resourceKey=job.resource_key,
        status=job.status,
        progressCurrent=job.progress_current,
        progressTotal=job.progress_total,
        progressMessage=job.progress_message,
        attemptCount=job.attempt_count,
        maxAttempts=job.max_attempts,
        result=job.result or {},
        errorCode=job.error_code,
        errorMessage=job.error_message,
        cleanupStatus=job.cleanup_status,
        cleanupAttemptCount=job.cleanup_attempt_count,
        cleanupMaxAttempts=job.cleanup_max_attempts,
        cleanupAvailableAt=job.cleanup_available_at,
        cleanupError=job.cleanup_error,
        startedAt=job.started_at,
        completedAt=job.completed_at,
        createdAt=job.created_at,
        updatedAt=job.updated_at,
        events=[job_event_response(event) for event in events],
    )


async def get_operation_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> MCPOperationJobRead:
    job = await job_repository.get_job(
        session,
        job_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    if job is None:
        raise MCPOperationJobNotFoundError("MCP operation job not found")
    events = await job_repository.list_job_events(session, job.id)
    return job_response(job, events)
