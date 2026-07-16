import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.core.pagination import decode_cursor
from app.modules.mcp_gateway import repository
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion


class RowsResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class RecordingSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return RowsResult(self.rows)


def installation(name: str) -> MCPServerInstallation:
    now = datetime.now(UTC)
    return MCPServerInstallation(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        server_name=name,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        installed_at=now,
        created_at=now,
        updated_at=now,
    )


def server(name: str) -> MCPServerVersion:
    now = datetime.now(UTC)
    return MCPServerVersion(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name=name,
        version="1.0.0",
        description="Weather tools",
        server_json={},
        status="active",
        is_latest=True,
        published_at=now,
        status_changed_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_gateway_server_search_is_tenant_safe_indexed_and_keyset_paginated() -> None:
    rows = [
        (installation("example/alpha"), server("example/alpha")),
        (installation("example/beta"), server("example/beta")),
        (installation("example/gamma"), server("example/gamma")),
    ]
    session = RecordingSession(rows)

    page, next_cursor = await repository.search_enabled_installations(
        session,
        scope=GatewayScope(user_id=uuid.uuid4(), is_superuser=True),
        search="weather",
        cursor=None,
        limit=2,
    )

    assert page == rows[:2]
    assert decode_cursor(next_cursor, fields=2) == (
        rows[1][0].server_name,
        str(rows[1][0].id),
    )
    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "MCP_SERVER_VERSIONS.ORGANIZATION_ID = WORKSPACES.ORGANIZATION_ID" in sql
    assert "SEARCH_VECTOR @@ WEBSEARCH_TO_TSQUERY" in sql
    assert " OFFSET " not in sql
