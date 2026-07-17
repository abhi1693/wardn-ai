from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.mcp_registry.source_metadata_rate_limit import (
    consume_repository_metadata_rate_limit,
)


class _Result:
    def __init__(self, row) -> None:
        self.row = row

    def one(self):
        return self.row


class _Session:
    def __init__(self, row) -> None:
        self.row = row
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.row)


@pytest.mark.asyncio
async def test_rate_limit_uses_an_atomic_postgres_upsert() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    session = _Session((now, 11))

    result = await consume_repository_metadata_rate_limit(
        session,  # type: ignore[arg-type]
        uuid4(),
        limit=10,
        window_seconds=60,
        now=now,
    )

    sql = str(session.statement.compile(dialect=postgresql.dialect())).upper()
    assert "ON CONFLICT (ORGANIZATION_ID) DO UPDATE" in sql
    assert "RETURNING" in sql
    assert result.allowed is False
    assert result.retry_after_seconds == 61
