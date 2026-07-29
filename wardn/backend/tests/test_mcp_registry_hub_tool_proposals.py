from uuid import uuid4

import pytest

from app.core.config import Settings
from app.db.session import DEFERRED_SESSION_WORK_KEY
from app.modules.mcp_registry import hub_tool_proposals
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion


def make_settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def server_version(
    *,
    hub_version_id: str | None = None,
    server_json: dict | None = None,
) -> MCPServerVersion:
    hub_version_id = hub_version_id or str(uuid4())
    document = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "id": hub_version_id,
        "name": "io.github.example/weather",
        "title": "Weather",
        "description": "Weather tools",
        "version": "1.0.0",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/weather",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ],
        "_meta": {
            "categories": ["weather"],
            "wardnCatalogSource": {
                "provider": "wardn_hub",
                "baseUrl": "https://hub.wardnai.dev",
                "sourceUrl": "https://hub.wardnai.dev/api/v1/mcp/servers",
            },
        },
    }
    if server_json is not None:
        document.update(server_json)
    return MCPServerVersion(
        id=uuid4(),
        organization_id=uuid4(),
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools",
        version="1.0.0",
        server_json=document,
        is_latest=True,
        status="active",
        status_message="",
    )


def runtime_tools() -> list[dict]:
    return [
        {
            "name": "get_forecast",
            "description": "Get weather forecast",
            "inputSchema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
            "annotations": {"readOnlyHint": True},
        }
    ]


def test_hub_tool_inventory_proposal_event_skips_without_token() -> None:
    event = hub_tool_proposals.mcp_hub_tool_inventory_proposal_event(
        server_version(),
        tools=runtime_tools(),
        settings=make_settings(mcp_tool_proposal_api_token=""),
    )

    assert event is None


def test_hub_tool_inventory_proposal_event_targets_metadata_edit_endpoint() -> None:
    hub_id = str(uuid4())
    event = hub_tool_proposals.mcp_hub_tool_inventory_proposal_event(
        server_version(hub_version_id=hub_id),
        tools=runtime_tools(),
        settings=make_settings(mcp_tool_proposal_api_token="hub-token"),
    )

    assert event is not None
    assert event.url == "https://hub.wardnai.dev/api/v1/submissions/submit"
    assert event.server_name == "io.github.example/weather"
    assert event.server_version == "1.0.0"
    assert event.hub_version_id == hub_id
    assert event.server_json["name"] == "io.github.example/weather"
    assert event.server_json["version"] == "1.0.0"
    assert event.server_json["introspection"]["tools/list"]["tools"] == event.tools
    assert event.server_json["_meta"]["wardnAiToolInventory"]["hubVersionId"] == hub_id
    assert event.server_json["_meta"]["wardnAiToolInventory"]["inventoryHash"] == (
        event.inventory_hash
    )


def test_hub_tool_inventory_proposal_event_skips_matching_hub_tools() -> None:
    event = hub_tool_proposals.mcp_hub_tool_inventory_proposal_event(
        server_version(
            server_json={
                "introspection": {
                    "tools/list": {
                        "tools": runtime_tools(),
                    }
                },
            }
        ),
        tools=runtime_tools(),
        settings=make_settings(mcp_tool_proposal_api_token="hub-token"),
    )

    assert event is None


def test_tool_inventory_hash_is_stable_across_order_and_duplicates() -> None:
    tools = runtime_tools() + [
        {
            "name": "search_alerts",
            "description": "Search weather alerts",
            "inputSchema": {"type": "object"},
        }
    ]
    reversed_with_duplicate = [tools[1], tools[0], tools[0]]

    assert hub_tool_proposals.tool_inventory_hash(tools) == (
        hub_tool_proposals.tool_inventory_hash(reversed_with_duplicate)
    )


@pytest.mark.asyncio
async def test_queue_hub_tool_inventory_proposal_defers_work(monkeypatch) -> None:
    calls = []

    class FakeSession:
        def __init__(self) -> None:
            self.info = {}

    async def record_proposal(session, event, **kwargs):
        calls.append({"session": session, "event": event, "kwargs": kwargs})

    monkeypatch.setattr(
        hub_tool_proposals,
        "record_mcp_hub_tool_inventory_proposal",
        record_proposal,
    )
    session = FakeSession()
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version()

    queued = hub_tool_proposals.queue_mcp_hub_tool_inventory_proposal(
        session,
        installation=installation,
        server=server,
        tools=runtime_tools(),
        settings=make_settings(mcp_tool_proposal_api_token="hub-token"),
    )

    assert queued is True
    work = session.info[DEFERRED_SESSION_WORK_KEY][0]
    deferred_session = object()
    await work(deferred_session)

    assert calls[0]["session"] is deferred_session
    assert calls[0]["kwargs"]["installation_id"] == installation.id
    assert calls[0]["kwargs"]["workspace_id"] == installation.workspace_id
    assert calls[0]["kwargs"]["organization_id"] == server.organization_id
