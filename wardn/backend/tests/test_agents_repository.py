import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.agents import repository


class Result:
    def __init__(self, scalar=None, rows=None) -> None:
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return self.rows


class RecordingSession:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.statements = []
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)

    def add(self, value) -> None:
        value.id = value.id or uuid.uuid4()
        value.created_at = datetime.now(UTC)
        value.updated_at = datetime.now(UTC)
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def refresh(self, value) -> None:
        return None


@pytest.mark.asyncio
async def test_append_conversation_message_locks_parent_before_allocating_sequence() -> None:
    session = RecordingSession([Result(), Result(scalar=4)])
    conversation_id = uuid.uuid4()

    message = await repository.append_conversation_message(
        session,
        conversation_id=conversation_id,
        role="user",
        content="hello",
        parts=[],
    )

    lock_sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "FROM WORKSPACE_CONVERSATIONS" in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert message.sequence == 5


@pytest.mark.asyncio
async def test_append_agent_run_step_locks_parent_before_allocating_sequence() -> None:
    session = RecordingSession([Result(), Result(scalar=2)])
    run_id = uuid.uuid4()

    step = await repository.append_agent_run_step(
        session,
        agent_run_id=run_id,
        step_type="tool",
        status="running",
        title="Call tool",
        payload={},
    )

    lock_sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "FROM AGENT_RUNS" in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert step.sequence == 3
