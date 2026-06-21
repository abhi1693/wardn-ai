from fastapi import APIRouter

from app.modules.health.schemas import HealthStatus

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
)
async def ready() -> HealthStatus:
    return HealthStatus(status="ready")
