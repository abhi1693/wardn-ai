import json
import logging
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.outbound_http import open_outbound_request
from app.modules.mcp_gateway import repository as gateway_repository
from app.modules.mcp_gateway.client import MCPGatewayUnsupportedMethodError
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry import repository, tool_repository
from app.modules.mcp_registry.catalog_service import (
    CATALOG_SOURCE_META_KEY,
    catalog_source_auth_headers,
)
from app.modules.mcp_registry.hub_tool_proposals import (
    normalized_tools_from_server_json,
    queue_mcp_hub_tool_inventory_proposal,
    server_json_targets_installed_version,
    wardn_ai_user_agent,
)
from app.modules.mcp_registry.telemetry import hub_api_base_url, hub_source_metadata
from app.modules.mcp_runtime.manager import MCPRuntimeManager, get_runtime_manager
from app.modules.mcp_runtime.service import has_secret_handle_refs, list_tools_with_tracking

SYSTEM_SCOPE_USER_ID = UUID(int=0)
WARDN_HUB_TOOL_METADATA_TIMEOUT_SECONDS = 8.0
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPToolRefreshResult:
    server_name: str
    server_version: str
    tool_count: int
    source: str = "live-refresh"


async def refresh_tool_schemas(
    session: AsyncSession,
    server_name: str,
    *,
    workspace_id=None,
    runtime_manager: MCPRuntimeManager | None = None,
) -> MCPToolRefreshResult:
    row = await gateway_repository.get_enabled_installation(
        session,
        server_name,
        scope=GatewayScope(
            user_id=SYSTEM_SCOPE_USER_ID,
            is_superuser=True,
            workspace_id=workspace_id,
        ),
    )
    if row is None:
        raise LookupError("enabled MCP server was not found")

    installation, server = row
    return await refresh_tool_schemas_for_installation(
        session,
        installation=installation,
        server=server,
        runtime_manager=runtime_manager,
    )


async def refresh_tool_schemas_for_installation(
    session: AsyncSession,
    *,
    installation,
    server,
    runtime_manager: MCPRuntimeManager | None = None,
    prefer_registry_metadata: bool = True,
) -> MCPToolRefreshResult:
    if prefer_registry_metadata:
        registry_result = await seed_tool_schemas_from_registry_metadata(
            session,
            installation=installation,
            server=server,
        )
        if registry_result is not None:
            return registry_result

    manager = runtime_manager or get_runtime_manager()
    try:
        if has_secret_handle_refs(installation.secret_references):
            tools = await list_tools_with_tracking(
                session,
                installation,
                server,
                manager=manager,
            )
        else:
            try:
                await session.commit()
                tools = await run_in_threadpool(manager.list_tools, installation)
            except NotImplementedError:
                tools = await list_tools_with_tracking(
                    session,
                    installation,
                    server,
                    manager=manager,
                )
    except MCPGatewayUnsupportedMethodError:
        tools = []
    tool_count = await tool_repository.upsert_tool_schemas(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    queue_mcp_hub_tool_inventory_proposal(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    return MCPToolRefreshResult(
        server_name=server.name,
        server_version=server.version,
        tool_count=tool_count,
        source="live-refresh",
    )


async def seed_tool_schemas_from_registry_metadata(
    session: AsyncSession,
    *,
    installation,
    server,
) -> MCPToolRefreshResult | None:
    if (
        str(installation.server_name or "").strip() != server.name
        or str(installation.installed_version or "").strip() != server.version
        or not server_json_targets_installed_version(server)
    ):
        return None

    tools = normalized_tools_from_server_json(server.server_json)
    if not tools:
        hub_server_json = await fetch_hub_version_server_json(
            session,
            server=server,
        )
        if (
            hub_server_json is not None
            and hub_server_json.get("name") == server.name
            and hub_server_json.get("version") == server.version
        ):
            tools = normalized_tools_from_server_json(hub_server_json)
        if not tools:
            return None

    tool_count = await tool_repository.upsert_tool_schemas(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    source = "hub-metadata" if hub_source_metadata(server) is not None else "registry-metadata"
    return MCPToolRefreshResult(
        server_name=server.name,
        server_version=server.version,
        tool_count=tool_count,
        source=source,
    )


def hub_version_detail_url(source_url: str, server_name: str, version: str) -> str | None:
    split_url = urlsplit(source_url.strip())
    if split_url.scheme not in {"http", "https"} or not split_url.netloc:
        return None
    path = split_url.path.rstrip("/")
    if not path:
        return None
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            f"{path}/{quote(server_name, safe='/')}/versions/{quote(version, safe='')}",
            "",
            "",
        )
    )


def hub_version_detail_server_json(
    payload: Any,
    *,
    source_metadata: dict[str, str],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    version = payload.get("version")
    server = payload.get("server")
    if isinstance(version, dict):
        raw_server_json = version.get("serverJson")
        document = dict(raw_server_json) if isinstance(raw_server_json, dict) else {}
        server_payload = server if isinstance(server, dict) else {}
        for key in (
            "name",
            "title",
            "description",
            "documentation",
            "websiteUrl",
            "repository",
            "icons",
        ):
            if key not in document and key in server_payload:
                document[key] = server_payload[key]
        document["version"] = str(version.get("version") or document.get("version") or "").strip()
        version_id = str(version.get("id") or document.get("id") or "").strip()
        if version_id:
            document["id"] = version_id
        document["packages"] = version.get("packages", document.get("packages", [])) or []
        document["remotes"] = version.get("remotes", document.get("remotes", [])) or []
    elif isinstance(payload.get("serverJson"), dict):
        document = dict(payload["serverJson"])
    else:
        return None

    metadata = dict(document.get("_meta") or {})
    metadata[CATALOG_SOURCE_META_KEY] = dict(source_metadata)
    document["_meta"] = metadata
    return document


def fetch_hub_version_detail_payload(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float = WARDN_HUB_TOOL_METADATA_TIMEOUT_SECONDS,
) -> Any:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": wardn_ai_user_agent(get_settings()),
    }
    request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with open_outbound_request(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


async def hub_catalog_source_headers(
    session: AsyncSession,
    *,
    server,
    source_metadata: dict[str, str],
) -> dict[str, str]:
    source_id = getattr(server, "catalog_source_id", None)
    if source_id is None:
        try:
            source_id = uuid.UUID(str(source_metadata.get("id") or "").strip())
        except ValueError:
            return {}
    source = await repository.get_catalog_source(
        session,
        source_id,
        organization_id=server.organization_id,
    )
    if source is None or source.provider != "wardn_hub":
        return {}
    try:
        return await catalog_source_auth_headers(session, server.organization_id, source)
    except ValueError as exc:
        logger.info(
            "Unable to load Wardn Hub catalog source auth for tool metadata lookup.",
            extra={
                "organization_id": str(server.organization_id),
                "mcp_registry_server_name": server.name,
                "mcp_registry_version": server.version,
                "mcp_catalog_source_id": str(source.id),
                "mcp_registry_error": str(exc),
            },
        )
        return {}


async def fetch_hub_version_server_json(
    session: AsyncSession,
    *,
    server,
) -> dict[str, Any] | None:
    source_metadata = hub_source_metadata(server)
    if source_metadata is None:
        return None

    source_url = hub_tool_metadata_source_url(source_metadata)
    url = hub_version_detail_url(source_url, server.name, server.version)
    if url is None:
        return None

    headers = await hub_catalog_source_headers(
        session,
        server=server,
        source_metadata=source_metadata,
    )
    fetch_payload = partial(
        fetch_hub_version_detail_payload,
        url,
        headers=headers,
        timeout_seconds=WARDN_HUB_TOOL_METADATA_TIMEOUT_SECONDS,
    )
    try:
        payload = await run_in_threadpool(fetch_payload)
    except (HTTPError, URLError, ValueError, OSError) as exc:
        logger.info(
            "Unable to load Wardn Hub tool metadata; falling back to runtime discovery.",
            extra={
                "organization_id": str(server.organization_id),
                "mcp_registry_server_name": server.name,
                "mcp_registry_version": server.version,
                "mcp_registry_error": str(exc),
            },
        )
        return None
    return hub_version_detail_server_json(
        payload,
        source_metadata=source_metadata,
    )


def hub_tool_metadata_source_url(source_metadata: dict[str, str]) -> str:
    source_url = source_metadata.get("sourceUrl") or ""
    if source_url.strip():
        return source_url

    api_base_url = hub_api_base_url(source_metadata.get("baseUrl") or "")
    if api_base_url is None:
        return ""
    return f"{api_base_url}/mcp/servers"
