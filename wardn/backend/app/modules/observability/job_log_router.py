from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import require_organization_admin_or_404
from app.db.session import get_db_session
from app.modules.observability import job_log_service as service
from app.modules.observability.job_log_schemas import RuntimeLogPage
from app.modules.observability.job_logs import JobKind
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/organizations/{organization_id}/runtime-logs", tags=["runtime-logs"])
Cursor = Annotated[int | None, Query(ge=0, le=9_223_372_036_854_775_807)]
PageSize = Annotated[int, Query(ge=1, le=500)]


@router.get(
    "/catalog-sources/{source_id}",
    response_model=RuntimeLogPage,
    operation_id="catalog_source_runtime_logs",
)
async def catalog_source_logs(
    organization_id: UUID,
    source_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    after: Cursor = None,
    limit: PageSize = 100,
) -> RuntimeLogPage:
    await require_organization_admin_or_404(session, current_user, organization_id)
    response.headers["Cache-Control"] = "no-store"
    job = await service.latest_catalog_job(session, organization_id, source_id)
    return await service.read_logs(
        session, organization_id, "mcp_operation", job, after=after, limit=limit
    )


@router.get("/{kind}/{job_id}", response_model=RuntimeLogPage, operation_id="job_runtime_logs")
async def job_logs(
    organization_id: UUID,
    kind: JobKind,
    job_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    after: Cursor = None,
    limit: PageSize = 100,
) -> RuntimeLogPage:
    await require_organization_admin_or_404(session, current_user, organization_id)
    response.headers["Cache-Control"] = "no-store"
    job = await service.get_log_job(session, organization_id, kind, job_id)
    return await service.read_logs(session, organization_id, kind, job, after=after, limit=limit)
