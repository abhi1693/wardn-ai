from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.agents import repository as agent_repository
from app.modules.agents.models import Agent
from app.modules.mcp_registry import repository as registry_repository
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion


class RowsResult:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def all(self) -> list[tuple]:
        return self.rows


class QueryCountingSession:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return RowsResult(self.rows)


@pytest.mark.asyncio
async def test_agent_listing_loads_assignment_counts_in_one_query() -> None:
    organization_id = uuid4()
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        name="Assistant",
        instructions="Help.",
        scope="organization",
        is_active=True,
    )
    session = QueryCountingSession([(agent, 2, 7)])

    rows, next_cursor = await agent_repository.list_agents(
        session,
        organization_id=organization_id,
        user_id=uuid4(),
        is_superuser=True,
    )

    assert rows == [(agent, 2, 7)]
    assert next_cursor == ""
    assert len(session.statements) == 1
    sql = str(session.statements[0])
    assert "agent_mcp_server_assignments" in sql
    assert "agent_mcp_tool_assignments" in sql
    assert "count(distinct" in sql.lower()


@pytest.mark.asyncio
async def test_installation_listing_loads_installed_and_latest_versions_in_one_query() -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installed = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version="1.0.0",
        description="Weather",
        server_json={},
        status="active",
        is_latest=False,
        published_at=datetime.now(UTC),
        status_changed_at=datetime.now(UTC),
    )
    latest = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version="1.1.0",
        description="Weather",
        server_json={},
        status="active",
        is_latest=True,
        published_at=datetime.now(UTC),
        status_changed_at=datetime.now(UTC),
    )
    session = QueryCountingSession([(installation, installed, latest)])

    rows, next_cursor = await registry_repository.list_installation_version_rows(
        session,
        workspace_id,
    )

    assert rows == [(installation, installed, latest)]
    assert next_cursor == ""
    assert len(session.statements) == 1
    sql = str(session.statements[0])
    assert "installed_version" in sql
    assert "latest_version" in sql
