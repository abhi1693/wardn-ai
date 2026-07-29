"""Best-effort MCP registry telemetry helpers."""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

from app.core.config import Settings, get_settings
from app.core.outbound_http import open_outbound_request
from app.modules.mcp_registry.catalog_service import CATALOG_SOURCE_META_KEY
from app.modules.mcp_registry.models import MCPServerVersion

WARDN_HUB_TELEMETRY_PATH = "/mcp/servers/telemetry"
WARDN_HUB_TELEMETRY_TIMEOUT_SECONDS = 3.0
TELEMETRY_CLIENT_VALUE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPServerInstallTelemetryEvent:
    url: str
    server_name: str
    version: str
    hub_version_id: str
    client: str
    client_version: str


def hub_source_metadata(server: MCPServerVersion) -> dict[str, str] | None:
    metadata = server.server_json.get("_meta")
    if not isinstance(metadata, dict):
        return None
    source_metadata = metadata.get(CATALOG_SOURCE_META_KEY)
    if not isinstance(source_metadata, dict):
        return None
    if source_metadata.get("provider") != "wardn_hub":
        return None
    return {str(key): str(value) for key, value in source_metadata.items() if value is not None}


def hub_version_id(server: MCPServerVersion) -> str | None:
    value = server.server_json.get("id")
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def hub_api_base_url(value: str) -> str | None:
    split_url = urlsplit(value.strip().rstrip("/"))
    if split_url.scheme not in {"http", "https"} or not split_url.netloc:
        return None
    return f"{split_url.scheme}://{split_url.netloc}/api/v1"


def telemetry_client(install_type: str) -> str:
    normalized = TELEMETRY_CLIENT_VALUE_PATTERN.sub("-", install_type.strip().casefold())
    normalized = normalized.strip(".-_") or "unknown"
    return f"wardn-ai-{normalized}"[:32]


def telemetry_client_version(settings: Settings) -> str:
    normalized = TELEMETRY_CLIENT_VALUE_PATTERN.sub("-", settings.app_version.strip())
    normalized = normalized.strip(".-_")
    return normalized[:32] if normalized else "unknown"


def telemetry_server_path(server_name: str) -> str:
    return "/".join(quote(part, safe="") for part in server_name.split("/"))


def mcp_server_install_telemetry_event(
    server: MCPServerVersion,
    *,
    install_type: str,
    settings: Settings | None = None,
) -> MCPServerInstallTelemetryEvent | None:
    settings = settings or get_settings()
    if not settings.telemetry:
        return None

    source_metadata = hub_source_metadata(server)
    if source_metadata is None:
        return None

    base_url = source_metadata.get("baseUrl") or source_metadata.get("sourceUrl") or ""
    api_base_url = hub_api_base_url(base_url)
    version_id = hub_version_id(server)
    if api_base_url is None or version_id is None:
        return None

    client = telemetry_client(install_type)
    client_version = telemetry_client_version(settings)
    query = urlencode(
        {
            "version_id": version_id,
            "client": client,
            "client_version": client_version,
        }
    )
    return MCPServerInstallTelemetryEvent(
        url=(
            f"{api_base_url}{WARDN_HUB_TELEMETRY_PATH}/"
            f"{telemetry_server_path(server.name)}?{query}"
        ),
        server_name=server.name,
        version=server.version,
        hub_version_id=version_id,
        client=client,
        client_version=client_version,
    )


def post_mcp_server_install_telemetry_event(event: MCPServerInstallTelemetryEvent) -> None:
    request = Request(event.url, method="POST")
    with open_outbound_request(
        request,
        timeout=WARDN_HUB_TELEMETRY_TIMEOUT_SECONDS,
    ) as response:
        response.read()


async def record_mcp_server_install_telemetry(
    event: MCPServerInstallTelemetryEvent,
) -> None:
    try:
        await asyncio.to_thread(post_mcp_server_install_telemetry_event, event)
    except Exception as exc:  # pragma: no cover - defensive best-effort boundary.
        logger.warning(
            "Failed to record MCP server install telemetry.",
            extra={
                "mcp_server_name": event.server_name,
                "mcp_server_version": event.version,
                "mcp_registry_version_id": event.hub_version_id,
                "mcp_telemetry_client": event.client,
                "mcp_telemetry_error": str(exc),
            },
        )
        return

    logger.info(
        "Recorded MCP server install telemetry.",
        extra={
            "mcp_server_name": event.server_name,
            "mcp_server_version": event.version,
            "mcp_registry_version_id": event.hub_version_id,
            "mcp_telemetry_client": event.client,
        },
    )


def schedule_mcp_server_install_telemetry(
    server: MCPServerVersion,
    *,
    install_type: str,
    settings: Settings | None = None,
) -> asyncio.Task[None] | None:
    event = mcp_server_install_telemetry_event(
        server,
        install_type=install_type,
        settings=settings,
    )
    if event is None:
        return None
    return asyncio.create_task(record_mcp_server_install_telemetry(event))
