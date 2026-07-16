import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry.models import MCPOperationJob, MCPOperationJobEvent


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
