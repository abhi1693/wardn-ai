from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.organizations import repository


class ListResult:
    def __init__(self, values=None) -> None:
        self.values = values or []

    def all(self):
        return self.values

    def scalars(self):
        return self


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


@pytest.mark.asyncio
async def test_sole_workspace_owner_query_is_scoped_to_active_organization_workspaces() -> None:
    session = RecordingSession()
    organization_id = uuid4()
    user_id = uuid4()

    workspace_ids = await repository.list_sole_owned_workspace_ids_for_organization_user(
        session,
        organization_id=organization_id,
        user_id=user_id,
    )

    assert workspace_ids == []
    assert len(session.statements) == 1
    statement_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "workspaces.organization_id" in statement_sql
    assert "workspaces.status" in statement_sql
    assert "workspace_memberships.role" in statement_sql
    assert "owner_count" in statement_sql
