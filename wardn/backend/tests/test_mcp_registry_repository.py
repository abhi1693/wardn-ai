from datetime import UTC, datetime
from decimal import Decimal
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


def server(
    name: str,
    version: str,
    *,
    quality_score: int | None = None,
) -> MCPServerVersion:
    now = datetime.now(UTC)
    server_json = {}
    if quality_score is not None:
        server_json = {
            "_meta": {
                "dev.wardnai.hub/catalog": {
                    "qualityScore": quality_score,
                },
            },
        }
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
        server_json=server_json,
        published_at=now,
        status_changed_at=now,
        created_at=now,
        updated_at=now,
    )


def sql(statement: object, *, literal_binds: bool = False) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": literal_binds},
        )
    )


def test_registry_search_normalization_drops_only_generic_catalog_terms() -> None:
    assert repository.normalize_registry_search_query("argocd") == "argocd"
    assert repository.normalize_registry_search_query("ArgoCD MCP Server") == "argocd"
    assert (
        repository.normalize_registry_search_query("ArgoCD Model Context Protocol server")
        == "argocd"
    )
    assert repository.normalize_registry_search_query("mcp server") == "mcp server"
    assert (
        repository.normalize_registry_search_query("cloudformation best practices")
        == "cloudformation best practices"
    )


@pytest.mark.asyncio
async def test_list_servers_uses_search_index_and_keyset_cursor() -> None:
    organization_id = uuid4()
    servers = [
        server("example/alpha", "1.0.0", quality_score=95),
        server("example/beta", "1.0.0", quality_score=84),
        server("example/gamma", "1.0.0"),
    ]
    rows = [
        (servers[0], 0, 0.8, Decimal("-95")),
        (servers[1], 1, 0.4, Decimal("-84")),
        (servers[2], 3, 0.1, repository.NULL_QUALITY_SCORE_RANK),
    ]
    session = RecordingSession(rows)

    page, next_cursor = await repository.list_servers(
        session,
        cursor=None,
        limit=2,
        include_deleted=False,
        search="weather forecast mcp server",
        organization_id=organization_id,
    )

    assert page == servers[:2]
    assert decode_cursor(next_cursor, fields=6) == (
        "1",
        (0.4).hex(),
        "-84",
        servers[1].name,
        servers[1].version,
        str(servers[1].id),
    )
    statement_sql = sql(session.statements[0], literal_binds=True).upper()
    assert (
        "MCP_SERVER_VERSIONS.SEARCH_VECTOR @@ "
        "WEBSEARCH_TO_TSQUERY('ENGLISH'::REGCONFIG, 'WEATHER FORECAST')" in statement_sql
    )
    assert (
        "MCP_SERVER_VERSIONS.SEARCH_VECTOR @@ "
        "WEBSEARCH_TO_TSQUERY('SIMPLE'::REGCONFIG, 'WEATHER FORECAST')" in statement_sql
    )
    assert "WEATHER FORECAST MCP SERVER" not in statement_sql
    assert "TS_RANK_CD(MCP_SERVER_VERSIONS.SEARCH_VECTOR" in statement_sql
    assert "LOWER(MCP_SERVER_VERSIONS.NAME)" in statement_sql
    assert "LOWER(MCP_SERVER_VERSIONS.TITLE)" in statement_sql
    assert "MCP_SERVER_VERSIONS.DESCRIPTION ILIKE" not in statement_sql
    assert "CASE WHEN" in statement_sql
    assert (
        "ORDER BY COALESCE(-COALESCE("
        in statement_sql
        and "MATCH_TIER ASC, TEXT_RANK DESC" in statement_sql
    )
    assert statement_sql.index("ORDER BY COALESCE(-COALESCE(") < statement_sql.index(
        "MATCH_TIER ASC"
    )
    assert "MCP_SERVER_VERSIONS.NAME ASC" in statement_sql
    assert "MCP_SERVER_VERSIONS.ID ASC" in statement_sql
    assert " OFFSET " not in statement_sql

    cursor = encode_cursor("-95", servers[0].name, servers[0].version, str(servers[0].id))
    session = RecordingSession([])
    await repository.list_servers(
        session,
        cursor=cursor,
        limit=2,
        include_deleted=False,
        organization_id=organization_id,
    )
    statement_sql = sql(session.statements[0]).upper()
    assert "(COALESCE(-COALESCE(" in statement_sql
    assert "MCP_SERVER_VERSIONS.NAME, MCP_SERVER_VERSIONS.VERSION, " in statement_sql
    assert ") > (" in statement_sql
    assert " OFFSET " not in statement_sql


@pytest.mark.asyncio
async def test_list_servers_search_cursor_uses_ranked_order() -> None:
    organization_id = uuid4()
    first = server("example/weather", "1.0.0", quality_score=90)
    cursor = encode_cursor("1", (0.5).hex(), "-90", first.name, first.version, str(first.id))
    session = RecordingSession([])

    await repository.list_servers(
        session,
        cursor=cursor,
        limit=2,
        include_deleted=False,
        search="weather",
        organization_id=organization_id,
    )

    statement_sql = sql(session.statements[0], literal_binds=True).upper()
    assert "TS_RANK_CD(MCP_SERVER_VERSIONS.SEARCH_VECTOR" in statement_sql
    assert "CASE WHEN" in statement_sql
    assert "COALESCE(-COALESCE(" in statement_sql and " > " in statement_sql
    assert "TS_RANK_CD" in statement_sql and " < " in statement_sql
    assert "MCP_SERVER_VERSIONS.NAME > 'EXAMPLE/WEATHER'" in statement_sql
    assert " OFFSET " not in statement_sql


@pytest.mark.asyncio
async def test_list_servers_rejects_invalid_keyset_uuid() -> None:
    cursor = encode_cursor("-42", "example/weather", "1.0.0", "not-a-uuid")

    with pytest.raises(InvalidCursorError):
        await repository.list_servers(
            RecordingSession(),
            cursor=cursor,
            limit=50,
            include_deleted=False,
            organization_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_list_servers_rejects_invalid_search_keyset_uuid() -> None:
    cursor = encode_cursor("0", (0.5).hex(), "-42", "example/weather", "1.0.0", "bad")

    with pytest.raises(InvalidCursorError):
        await repository.list_servers(
            RecordingSession(),
            cursor=cursor,
            limit=50,
            include_deleted=False,
            search="weather",
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
