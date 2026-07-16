from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry import repository, tool_repository
from app.modules.mcp_registry.models import MCPServerToolSchema, MCPServerVersion


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


def server(name: str, version: str) -> MCPServerVersion:
    now = datetime.now(UTC)
    return MCPServerVersion(
        id=uuid4(),
        organization_id=uuid4(),
        catalog_source_id=None,
        name=name,
        title="",
        description="Weather tools",
        version=version,
        website_url="",
        status="active",
        status_message="",
        is_latest=True,
        repository=None,
        packages=[],
        remotes=[],
        icons=[],
        server_json={},
        published_at=now,
        status_changed_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_servers_uses_search_index_and_keyset_cursor() -> None:
    organization_id = uuid4()
    rows = [
        server("example/alpha", "1.0.0"),
        server("example/beta", "1.0.0"),
        server("example/gamma", "1.0.0"),
    ]
    session = RecordingSession(rows)

    page, next_cursor = await repository.list_servers(
        session,
        cursor=None,
        limit=2,
        include_deleted=False,
        search="weather forecast",
        organization_id=organization_id,
    )

    assert page == rows[:2]
    assert decode_cursor(next_cursor, fields=3) == (
        rows[1].name,
        rows[1].version,
        str(rows[1].id),
    )
    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "SEARCH_VECTOR @@ WEBSEARCH_TO_TSQUERY" in sql
    assert "ORDER BY MCP_SERVER_VERSIONS.NAME ASC" in sql
    assert "MCP_SERVER_VERSIONS.ID ASC" in sql
    assert " OFFSET " not in sql

    cursor = encode_cursor(rows[0].name, rows[0].version, str(rows[0].id))
    session = RecordingSession([])
    await repository.list_servers(
        session,
        cursor=cursor,
        limit=2,
        include_deleted=False,
        organization_id=organization_id,
    )
    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "(MCP_SERVER_VERSIONS.NAME, MCP_SERVER_VERSIONS.VERSION, " in sql
    assert ") > (" in sql
    assert " OFFSET " not in sql


@pytest.mark.asyncio
async def test_list_servers_rejects_invalid_keyset_uuid() -> None:
    cursor = encode_cursor("example/weather", "1.0.0", "not-a-uuid")

    with pytest.raises(InvalidCursorError):
        await repository.list_servers(
            RecordingSession(),
            cursor=cursor,
            limit=50,
            include_deleted=False,
            organization_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_catalog_source_lookup_uses_normalized_column() -> None:
    session = RecordingSession()

    await repository.list_server_versions_for_catalog_source(
        session,
        organization_id=uuid4(),
        source_id=uuid4(),
    )

    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "MCP_SERVER_VERSIONS.CATALOG_SOURCE_ID" in sql
    assert "SERVER_JSON @>" not in sql


def test_bulk_upsert_is_one_conflict_aware_statement() -> None:
    organization_id = uuid4()
    now = datetime.now(UTC)
    rows = [
        {
            "id": uuid4(),
            "organization_id": organization_id,
            "catalog_source_id": None,
            "name": "example/weather",
            "title": "Weather",
            "description": "Forecast tools",
            "version": version,
            "website_url": "",
            "repository": None,
            "packages": [],
            "remotes": [],
            "icons": [],
            "server_json": {},
            "status": "active",
            "status_message": "",
            "is_latest": version == "2.0.0",
            "published_at": now,
            "status_changed_at": now,
        }
        for version in ("1.0.0", "2.0.0")
    ]

    statement = repository.bulk_upsert_server_versions_statement(
        rows,
        update_published_metadata=False,
    )
    sql = str(statement.compile(dialect=postgresql.dialect())).upper()

    assert sql.startswith("INSERT INTO MCP_SERVER_VERSIONS")
    assert "ON CONFLICT ON CONSTRAINT UQ_MCP_SERVER_VERSIONS_ORG_NAME_VERSION" in sql
    assert "DO UPDATE SET" in sql
    assert "CATALOG_SOURCE_ID = EXCLUDED.CATALOG_SOURCE_ID" in sql


@pytest.mark.asyncio
async def test_tool_search_uses_search_index_and_keyset_cursor() -> None:
    now = datetime.now(UTC)
    tools = [
        MCPServerToolSchema(
            id=uuid4(),
            installation_id=uuid4(),
            workspace_id=uuid4(),
            server_name="example/weather",
            server_version="1.0.0",
            tool_name=name,
            title=name,
            description="Weather tool",
            is_active=True,
            discovered_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        for name in ("forecast", "history", "radar")
    ]
    session = RecordingSession(tools)

    page, next_cursor = await tool_repository.search_enabled_tool_schemas(
        session,
        scope=GatewayScope(user_id=uuid4(), is_superuser=True),
        server_name="example/weather",
        search="forecast",
        cursor=None,
        limit=2,
    )

    assert page == tools[:2]
    assert decode_cursor(next_cursor, fields=3) == (
        tools[1].server_name,
        tools[1].tool_name,
        str(tools[1].id),
    )
    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).upper()
    assert "SEARCH_VECTOR @@ WEBSEARCH_TO_TSQUERY" in sql
    assert "ORDER BY MCP_SERVER_TOOL_SCHEMAS.SERVER_NAME ASC" in sql
    assert " OFFSET " not in sql
