from app.core.schemas import APIModel


class HealthStatus(APIModel):
    status: str
