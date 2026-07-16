from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.mcp_runtime import repository


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class RecordingSession:
    def __init__(self, values=None) -> None:
        self.values = values or []
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return ScalarResult(self.values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("delete_batch", "table_name", "timestamp_column"),
    (
        (
            repository.delete_runtime_events_before,
            "mcp_runtime_events",
            "created_at",
        ),
        (
            repository.delete_tool_invocations_before,
            "mcp_tool_invocations",
            "started_at",
        ),
    ),
)
async def test_retention_delete_uses_bounded_skip_locked_cte(
    delete_batch,
    table_name,
    timestamp_column,
) -> None:
    deleted_ids = [uuid4(), uuid4()]
    session = RecordingSession(deleted_ids)

    deleted_count = await delete_batch(
        session,
        cutoff=datetime.now(UTC),
        limit=2,
    )

    assert deleted_count == 2
    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).lower()
    assert "with expired_rows as" in sql
    assert f"from {table_name}" in sql
    assert f"{table_name}.{timestamp_column} <" in sql
    assert f"order by {table_name}.{timestamp_column} asc, {table_name}.id asc" in sql
    assert "limit" in sql
    assert "for update skip locked" in sql
    assert f"delete from {table_name}" in sql
    assert "returning" in sql


@pytest.mark.asyncio
async def test_retention_delete_rejects_empty_batch() -> None:
    session = RecordingSession()

    deleted_count = await repository.delete_runtime_events_before(
        session,
        cutoff=datetime.now(UTC),
        limit=0,
    )

    assert deleted_count == 0
    assert session.statements == []
