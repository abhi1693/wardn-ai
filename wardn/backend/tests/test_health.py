from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.health import router as health_router


def test_live_health() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_health_checks_database(monkeypatch) -> None:
    async def database_is_ready() -> bool:
        return True

    monkeypatch.setattr(health_router, "database_is_ready", database_is_ready)
    response = TestClient(create_app()).get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_health_is_unavailable_when_database_check_fails(monkeypatch) -> None:
    async def database_is_ready() -> bool:
        return False

    monkeypatch.setattr(health_router, "database_is_ready", database_is_ready)
    response = TestClient(create_app()).get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
