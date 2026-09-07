import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.agents.models import AgentRun
from app.modules.mcp_registry.models import MCPCatalogSource, MCPOperationJob
from app.modules.observability.job_log_schemas import (
    RuntimeLogEntry,
    RuntimeLogPage,
    StoredLogEntry,
)
from app.modules.observability.job_logs import JobKind
from app.modules.observability.models import RuntimeJobLog
from app.modules.scheduled_tasks.models import WorkspaceScheduledTaskRun

JOB_MODELS = {
    "mcp_operation": MCPOperationJob,
    "scheduled_task": WorkspaceScheduledTaskRun,
    "agent_run": AgentRun,
}


async def get_log_job(session, organization_id: uuid.UUID, kind: JobKind, job_id: uuid.UUID):
    model = JOB_MODELS[kind]
    job = await session.scalar(
        select(model).where(model.organization_id == organization_id, model.id == job_id)
    )
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


async def latest_catalog_job(session, organization_id: uuid.UUID, source_id: uuid.UUID):
    source = await session.scalar(
        select(MCPCatalogSource.id).where(
            MCPCatalogSource.organization_id == organization_id, MCPCatalogSource.id == source_id
        )
    )
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    return await session.scalar(
        select(MCPOperationJob)
        .where(
            MCPOperationJob.organization_id == organization_id,
            MCPOperationJob.operation == "sync_catalog_source",
            MCPOperationJob.request_payload["sourceId"].astext == str(source_id),
        )
        .order_by(MCPOperationJob.created_at.desc(), MCPOperationJob.id.desc())
        .limit(1)
    )


async def read_logs(
    session: AsyncSession,
    organization_id: uuid.UUID,
    kind: JobKind,
    job,
    *,
    after: int | None,
    limit: int,
) -> RuntimeLogPage:
    settings = get_settings()
    page = RuntimeLogPage(
        job_id=job.id if job else None,
        job_status=job.status if job else None,
        items=[],
        next_cursor=str(after) if after is not None else None,
        has_more=False,
        truncated=False,
        unreadable_entries=0,
        retention_seconds=settings.job_log_ttl_seconds,
        max_entries=settings.job_log_max_entries,
    )
    if job is None:
        return page
    scope = (
        RuntimeJobLog.organization_id == organization_id,
        RuntimeJobLog.job_kind == kind,
        RuntimeJobLog.job_id == job.id,
        RuntimeJobLog.expires_at > func.now(),
    )
    statement = select(RuntimeJobLog).where(*scope)
    if after is not None:
        statement = statement.where(RuntimeJobLog.id > after)
    try:
        rows = list(await session.scalars(statement.order_by(RuntimeJobLog.id).limit(limit + 1)))
        count = await session.scalar(select(func.count()).select_from(RuntimeJobLog).where(*scope))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Runtime log storage is temporarily unavailable") from exc
    page.has_more = len(rows) > limit
    page.truncated = (count or 0) >= settings.job_log_max_entries
    for row in rows[:limit]:
        page.next_cursor = str(row.id)
        try:
            entry = StoredLogEntry.model_validate(row.entry)
        except ValidationError:
            page.unreadable_entries += 1
            continue
        page.items.append(RuntimeLogEntry(id=str(row.id), **entry.model_dump()))
    return page
