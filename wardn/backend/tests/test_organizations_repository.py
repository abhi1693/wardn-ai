from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.organizations import repository


class ListResult:
    def __init__(self, values=None) -> None:
        self.values = values or []

    def all(self):
        return self.values


class RecordingSession:
    def __init__(self, values=None) -> None:
        self.values = values or []
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return ListResult(self.values)


@pytest.mark.asyncio
async def test_list_workspace_members_orders_by_real_user_columns() -> None:
    session = RecordingSession()

    members = await repository.list_workspace_members(
        session,
        organization_id=uuid4(),
        workspace_id=uuid4(),
    )

    assert members == []
    assert len(session.statements) == 1
    statement_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "users.first_name" in statement_sql
    assert "users.last_name" in statement_sql
    assert "users.email" in statement_sql
    assert "display_name" not in statement_sql
