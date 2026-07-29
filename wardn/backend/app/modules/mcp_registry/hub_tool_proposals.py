"""Best-effort Hub metadata proposals for runtime MCP tool inventories."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.outbound_http import open_outbound_request
from app.db.session import defer_session_work
from app.modules.mcp_registry.models import (
    MCPHubToolInventoryProposal,
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.mcp_registry.telemetry import (
    hub_api_base_url,
    hub_source_metadata,
    hub_version_id,
)

WARDN_HUB_SUBMISSION_PATH = "/submissions/submit"
WARDN_AI_TOOL_INVENTORY_META_KEY = "wardnAiToolInventory"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPHubToolInventoryProposalEvent:
    url: str
    api_token: str
    server_name: str
    server_version: str
    hub_version_id: str
    inventory_hash: str
    tools: list[dict[str, Any]]
    server_json: dict[str, Any]
    timeout_seconds: float
    user_agent: str

    @property
    def tool_count(self) -> int:
        return len(self.tools)


@dataclass(frozen=True)
class MCPHubToolInventoryProposalResponse:
    submission_id: str


class MCPHubToolInventoryProposalHTTPError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Hub submission returned HTTP {status_code}")


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def wardn_ai_user_agent(settings: Settings) -> str:
    return f"wardn-ai/{settings.app_version} (+https://github.com/abhi1693/wardn-ai)"


def record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        payload = value.model_dump(by_alias=True, exclude_none=True)
        if isinstance(payload, dict):
            return payload
    return {}


def tool_candidate_lists_from_value(value: Any) -> list[list[Any]]:
    if isinstance(value, list):
        return [value]
    if not isinstance(value, dict):
        return []

    result = value.get("result")
    if isinstance(result, dict):
        nested = tool_candidate_lists_from_value(result)
        if nested:
            return nested

    tools = value.get("tools")
    if isinstance(tools, list):
        return [tools]
    return []


def registry_tool_candidate_lists(server_json: dict[str, Any]) -> list[list[Any]]:
    document = record(server_json)
    meta = record(document.get("_meta"))
    candidates: list[Any] = [
        document.get("tools"),
        document.get("toolDefinitions"),
        document.get("mcpTools"),
        record(document.get("capabilities")).get("tools"),
        record(document.get("introspection")).get("tools"),
        record(document.get("introspection")).get("tools/list"),
        record(document.get("tools/list")),
        record(document.get("mcp")).get("tools"),
        record(document.get("mcp")).get("tools/list"),
        meta.get("tools"),
        record(meta.get("capabilities")).get("tools"),
        record(meta.get("introspection")).get("tools"),
        record(meta.get("introspection")).get("tools/list"),
        record(meta.get("mcp")).get("tools"),
        record(meta.get("mcp")).get("tools/list"),
    ]

    lists: list[list[Any]] = []
    for candidate in candidates:
        lists.extend(tool_candidate_lists_from_value(candidate))
    return lists


def normalized_schema(value: Any) -> dict[str, Any]:
    return json_safe(value) if isinstance(value, dict) else {}


def normalized_tool(value: Any) -> dict[str, Any] | None:
    raw = record(value)
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    tool: dict[str, Any] = {
        "name": name,
        "title": str(raw.get("title") or ""),
        "description": str(raw.get("description") or ""),
        "inputSchema": normalized_schema(
            raw.get("inputSchema") or raw.get("input_schema") or raw.get("schema")
        ),
    }
    output_schema = normalized_schema(raw.get("outputSchema") or raw.get("output_schema"))
    if output_schema:
        tool["outputSchema"] = output_schema
    annotations = normalized_schema(raw.get("annotations"))
    for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
        if key in raw and key not in annotations:
            annotations[key] = json_safe(raw[key])
    if annotations:
        tool["annotations"] = annotations
    return tool


def normalized_tool_inventory(tools: list[Any]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for raw_tool in tools:
        tool = normalized_tool(raw_tool)
        if tool is not None and tool["name"] not in by_name:
            by_name[tool["name"]] = tool
    return [by_name[name] for name in sorted(by_name)]


def normalized_tools_from_server_json(server_json: dict[str, Any]) -> list[dict[str, Any]]:
    tools: list[Any] = []
    for candidate_list in registry_tool_candidate_lists(server_json):
        tools.extend(candidate_list)
    return normalized_tool_inventory(tools)


def tool_inventory_hash(tools: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        normalized_tool_inventory(tools),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hub_submission_url(server: MCPServerVersion) -> str | None:
    source_metadata = hub_source_metadata(server)
    if source_metadata is None:
        return None

    base_url = source_metadata.get("baseUrl") or source_metadata.get("sourceUrl") or ""
    api_base_url = hub_api_base_url(base_url)
    if api_base_url is None:
        return None
    return f"{api_base_url}{WARDN_HUB_SUBMISSION_PATH}"


def server_json_targets_installed_version(server: MCPServerVersion) -> bool:
    return (
        str(server.server_json.get("name") or "").strip() == server.name
        and str(server.server_json.get("version") or "").strip() == server.version
    )


def server_json_with_tool_inventory(
    server: MCPServerVersion,
    *,
    tools: list[dict[str, Any]],
    inventory_hash: str,
    hub_id: str,
) -> dict[str, Any]:
    document = copy.deepcopy(server.server_json)
    document["name"] = server.name
    document["version"] = server.version

    introspection = dict(document.get("introspection") or {})
    introspection["tools/list"] = {"tools": tools}
    document["introspection"] = introspection

    metadata = dict(document.get("_meta") or {})
    metadata[WARDN_AI_TOOL_INVENTORY_META_KEY] = {
        "source": "runtime_tools_list",
        "hubVersionId": hub_id,
        "inventoryHash": inventory_hash,
        "toolCount": len(tools),
        "observedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    document["_meta"] = metadata
    return document


def mcp_hub_tool_inventory_proposal_event(
    server: MCPServerVersion,
    *,
    tools: list[dict[str, Any]],
    settings: Settings | None = None,
) -> MCPHubToolInventoryProposalEvent | None:
    settings = settings or get_settings()
    if not settings.mcp_tool_proposal_enabled:
        return None

    api_token = settings.mcp_tool_proposal_api_token.get_secret_value().strip()
    if not api_token:
        return None
    if not tools or not server_json_targets_installed_version(server):
        return None

    url = hub_submission_url(server)
    hub_id = hub_version_id(server)
    if url is None or hub_id is None:
        return None

    observed_tools = normalized_tool_inventory(tools)
    if not observed_tools:
        return None
    observed_hash = tool_inventory_hash(observed_tools)
    if observed_hash == tool_inventory_hash(normalized_tools_from_server_json(server.server_json)):
        return None

    server_json = server_json_with_tool_inventory(
        server,
        tools=observed_tools,
        inventory_hash=observed_hash,
        hub_id=hub_id,
    )
    return MCPHubToolInventoryProposalEvent(
        url=url,
        api_token=api_token,
        server_name=server.name,
        server_version=server.version,
        hub_version_id=hub_id,
        inventory_hash=observed_hash,
        tools=observed_tools,
        server_json=server_json,
        timeout_seconds=settings.mcp_tool_proposal_timeout_seconds,
        user_agent=wardn_ai_user_agent(settings),
    )


async def existing_hub_tool_inventory_proposal(
    session: AsyncSession,
    *,
    event: MCPHubToolInventoryProposalEvent,
) -> MCPHubToolInventoryProposal | None:
    result = await session.execute(
        select(MCPHubToolInventoryProposal).where(
            MCPHubToolInventoryProposal.hub_version_id == event.hub_version_id,
            MCPHubToolInventoryProposal.inventory_hash == event.inventory_hash,
        )
    )
    return result.scalar_one_or_none()


async def reserve_hub_tool_inventory_proposal(
    session: AsyncSession,
    *,
    event: MCPHubToolInventoryProposalEvent,
    installation_id: Any = None,
    workspace_id: Any = None,
    organization_id: Any = None,
) -> MCPHubToolInventoryProposal | None:
    existing = await existing_hub_tool_inventory_proposal(session, event=event)
    if existing is not None:
        if existing.status != "failed":
            return None
        existing.organization_id = organization_id
        existing.workspace_id = workspace_id
        existing.installation_id = installation_id
        existing.tool_count = event.tool_count
        existing.status = "pending"
        existing.submission_id = ""
        existing.last_error = ""
        await session.flush()
        return existing

    proposal = MCPHubToolInventoryProposal(
        organization_id=organization_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name=event.server_name,
        server_version=event.server_version,
        hub_version_id=event.hub_version_id,
        inventory_hash=event.inventory_hash,
        tool_count=event.tool_count,
        status="pending",
        submission_id="",
        last_error="",
    )
    session.add(proposal)
    await session.flush()
    return proposal


def post_mcp_hub_tool_inventory_proposal(
    event: MCPHubToolInventoryProposalEvent,
) -> MCPHubToolInventoryProposalResponse:
    payload = json.dumps(
        {
            "submissionType": "metadata_edit",
            "serverJson": event.server_json,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        event.url,
        data=payload,
        headers={
            "Authorization": f"Bearer {event.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": event.user_agent,
        },
        method="POST",
    )
    try:
        with open_outbound_request(request, timeout=event.timeout_seconds) as response:
            body = response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise MCPHubToolInventoryProposalHTTPError(exc.code, body) from exc

    data = json.loads(body.decode("utf-8") or "{}")
    submission_id = str(data.get("id") or "")
    return MCPHubToolInventoryProposalResponse(submission_id=submission_id)


async def record_mcp_hub_tool_inventory_proposal(
    session: AsyncSession,
    event: MCPHubToolInventoryProposalEvent,
    *,
    installation_id: Any = None,
    workspace_id: Any = None,
    organization_id: Any = None,
) -> None:
    proposal = await reserve_hub_tool_inventory_proposal(
        session,
        event=event,
        installation_id=installation_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
    )
    if proposal is None:
        return

    try:
        response = await asyncio.to_thread(post_mcp_hub_tool_inventory_proposal, event)
    except MCPHubToolInventoryProposalHTTPError as exc:
        proposal.status = "skipped" if exc.status_code == 409 else "failed"
        proposal.last_error = f"HTTP {exc.status_code}: {exc.body}"[:2000]
        logger.warning(
            "Failed to submit MCP Hub tool inventory proposal.",
            extra={
                "mcp_server_name": event.server_name,
                "mcp_server_version": event.server_version,
                "mcp_registry_version_id": event.hub_version_id,
                "mcp_tool_inventory_hash": event.inventory_hash,
                "mcp_tool_proposal_status_code": exc.status_code,
            },
        )
    except Exception as exc:  # pragma: no cover - defensive best-effort boundary.
        proposal.status = "failed"
        proposal.last_error = str(exc)[:2000]
        logger.warning(
            "Failed to submit MCP Hub tool inventory proposal.",
            extra={
                "mcp_server_name": event.server_name,
                "mcp_server_version": event.server_version,
                "mcp_registry_version_id": event.hub_version_id,
                "mcp_tool_inventory_hash": event.inventory_hash,
                "mcp_tool_proposal_error": str(exc),
            },
        )
    else:
        proposal.status = "submitted"
        proposal.submission_id = response.submission_id
        proposal.last_error = ""
        proposal.submitted_at = datetime.now(UTC)
        logger.info(
            "Submitted MCP Hub tool inventory proposal.",
            extra={
                "mcp_server_name": event.server_name,
                "mcp_server_version": event.server_version,
                "mcp_registry_version_id": event.hub_version_id,
                "mcp_tool_inventory_hash": event.inventory_hash,
                "mcp_hub_submission_id": response.submission_id,
            },
        )
    await session.flush()


def queue_mcp_hub_tool_inventory_proposal(
    session: AsyncSession,
    *,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    tools: list[dict[str, Any]],
    settings: Settings | None = None,
) -> bool:
    event = mcp_hub_tool_inventory_proposal_event(
        server,
        tools=tools,
        settings=settings,
    )
    if event is None:
        return False

    async def submit_proposal(deferred_session: AsyncSession) -> None:
        await record_mcp_hub_tool_inventory_proposal(
            deferred_session,
            event,
            installation_id=installation.id,
            workspace_id=installation.workspace_id,
            organization_id=server.organization_id,
        )

    if not hasattr(session, "info"):
        return False
    defer_session_work(session, submit_proposal)
    return True
