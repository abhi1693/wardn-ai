import pytest
from sqlalchemy.exc import OperationalError

from app.modules.health.service import database_is_ready


class FakeConnection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.statements: list[object] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, statement) -> None:
        self.statements.append(statement)
        if self.error is not None:
            raise self.error


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> FakeConnection:
        return self.connection


@pytest.mark.asyncio
async def test_database_readiness_executes_select_one() -> None:
    connection = FakeConnection()

    assert await database_is_ready(FakeEngine(connection)) is True
    assert len(connection.statements) == 1
    assert str(connection.statements[0]) == "SELECT 1"


@pytest.mark.asyncio
async def test_database_readiness_handles_connection_errors() -> None:
    connection = FakeConnection(OperationalError("SELECT 1", {}, RuntimeError("offline")))

    assert await database_is_ready(FakeEngine(connection)) is False
