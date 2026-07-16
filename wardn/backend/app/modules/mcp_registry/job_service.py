import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry import job_repository
from app.modules.mcp_registry.exceptions import MCPOperationJobNotFoundError
from app.modules.mcp_registry.models import MCPOperationJob, MCPOperationJobEvent
from app.modules.mcp_registry.schemas import MCPOperationJobEventRead, MCPOperationJobRead


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
