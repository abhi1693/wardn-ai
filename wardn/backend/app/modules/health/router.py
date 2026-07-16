from fastapi import APIRouter, Response, status

from app.modules.health.schemas import HealthStatus
from app.modules.health.service import database_is_ready

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=HealthStatus,
    operation_id="health_live",
)
async def live() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/ready",
    response_model=HealthStatus,
    operation_id="health_ready",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthStatus,
            "description": "The database is unavailable.",
        }
    },
)
async def ready(response: Response) -> HealthStatus:
    if not await database_is_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="not_ready")
    return HealthStatus(status="ready")
