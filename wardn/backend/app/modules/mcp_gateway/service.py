import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.guardrails.service import (
    GUARDRAIL_MODE_ALLOW,
    GUARDRAIL_MODE_DENY,
    GUARDRAIL_MODE_REQUIRE_CONFIRMATION,
    GuardrailDecision,
    GuardrailEvaluationContext,
    evaluate_tool_call_guardrails,
)
from app.modules.mcp_gateway import repository
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_gateway.models import MCPGatewayToolApproval
from app.modules.mcp_gateway.schemas import (
    MCPGatewayToolApprovalDecisionRequest,
    MCPGatewayToolApprovalDecisionResponse,
    MCPGatewayToolApprovalListResponse,
    MCPGatewayToolApprovalRead,
)
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry import tool_repository
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas
from app.modules.mcp_runtime.manager import runtime_kind
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.mcp_runtime.service import (
    call_tool_with_isolated_tracking,
    tool_result_with_structured_content,
)
from app.modules.organizations import repository as organizations_repository
from app.modules.organizations.service import require_workspace_admin
from app.modules.users.models import User

PROTOCOL_VERSION = "2025-06-18"
MAX_SEARCH_LIMIT = 25


@dataclass(frozen=True)
class GatewayGuardrailTarget:
    tool_name: str
    arguments: dict[str, Any]
    wrapped_by: str | None = None

    @property
    def is_wrapped(self) -> bool:
        return self.wrapped_by is not None and self.wrapped_by != self.tool_name


def is_progress_token(value: Any) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def request_meta(params: dict[str, Any]) -> dict[str, Any]:
    meta = params.get("_meta")
    if meta is None:
        return {}
    if not isinstance(meta, dict):
        raise ValueError("_meta must be an object")
    if "progressToken" in meta and not is_progress_token(meta["progressToken"]):
        raise ValueError("progressToken must be a string or integer")
    return dict(meta)


def parse_cursor(cursor: Any) -> str | None:
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, str):
        raise ValueError("invalid cursor")
    return cursor


def bounded_limit(value: Any, *, default: int = 10) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be a number") from exc
    if limit < 1:
        raise ValueError("limit must be greater than 0")
    return min(limit, MAX_SEARCH_LIMIT)


def input_counts(server: MCPServerVersion) -> dict[str, int]:
    headers = [
        item
        for remote in server.remotes or []
        for item in remote.get("headers", [])
        if isinstance(item, dict)
    ]
    environment = [
        item
        for package in server.packages or []
        for item in package.get("environmentVariables", [])
        if isinstance(item, dict)
    ]
    arguments = [
        item
        for package in server.packages or []
        for item in package.get("packageArguments", [])
        if isinstance(item, dict)
    ]
    inputs = [*headers, *environment, *arguments]
    return {
        "total": len(inputs),
        "required": sum(1 for item in inputs if item.get("isRequired")),
        "secret": sum(1 for item in inputs if item.get("isSecret")),
    }


def server_summary(
    installation: MCPServerInstallation,
    server: MCPServerVersion,
) -> dict[str, Any]:
    return {
        "installationId": str(installation.id),
        "workspaceId": str(installation.workspace_id),
        "serverName": server.name,
        "title": server.title or server.name,
        "description": server.description,
        "version": server.version,
        "runtime": runtime_kind(installation),
        "status": installation.status,
        "inputCounts": input_counts(server),
    }


def server_detail(
    installation: MCPServerInstallation,
    server: MCPServerVersion,
) -> dict[str, Any]:
    runtime_config = installation.runtime_config or {}
    return {
        **server_summary(installation, server),
        "installedAt": installation.installed_at.isoformat() if installation.installed_at else "",
        "transport": runtime_config.get("transport", {}),
        "package": runtime_config.get("package", {}),
        "verification": runtime_config.get("verification", {}),
        "source": {
            "websiteUrl": server.website_url,
            "repository": server.repository,
        },
    }


def cached_tool_summary(tool: MCPServerToolSchema) -> dict[str, Any]:
    return {
        "installationId": str(tool.installation_id) if tool.installation_id else "",
        "workspaceId": str(tool.workspace_id) if tool.workspace_id else "",
        "serverName": tool.server_name,
        "toolName": tool.tool_name,
        "title": tool.title or tool.tool_name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
    }


def gateway_guardrail_target(tool_name: str, arguments: dict[str, Any]) -> GatewayGuardrailTarget:
    suffix = "_execute"
    if not tool_name.endswith(suffix):
        return GatewayGuardrailTarget(tool_name=tool_name, arguments=arguments)

    prefix = tool_name[: -len(suffix)]
    nested_tool = arguments.get("tool")
    if not isinstance(nested_tool, str):
        return GatewayGuardrailTarget(tool_name=tool_name, arguments=arguments)

    nested_tool = nested_tool.strip()
    if not nested_tool or not nested_tool.startswith(f"{prefix}_"):
        return GatewayGuardrailTarget(tool_name=tool_name, arguments=arguments)

    nested_arguments = arguments.get("arguments")
    if not isinstance(nested_arguments, dict):
        nested_arguments = {}

    return GatewayGuardrailTarget(
        tool_name=nested_tool,
        arguments=nested_arguments,
        wrapped_by=tool_name,
    )


def guardrail_target_payload(target: GatewayGuardrailTarget) -> dict[str, Any]:
    if not target.is_wrapped:
        return {}
    return {
        "evaluatedToolName": target.tool_name,
        "wrappedToolName": target.wrapped_by,
    }


def text_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def error_tool_result(message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    structured_content = payload or {}
    return {
        "content": [
            {
                "type": "text",
                "text": message,
            }
        ],
        "structuredContent": structured_content,
        "isError": True,
    }


def guardrail_payload(
    decision: GuardrailDecision,
    *,
    status: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "mode": decision.mode,
        "policyId": str(decision.policy_id) if decision.policy_id else "",
        "policyName": decision.policy_name,
        "message": message,
        "matchedPolicyIds": [
            str(policy_id) for policy_id in decision.matched_policy_ids
        ],
    }


def gateway_approval_url(approval: MCPGatewayToolApproval) -> str:
    base_url = get_settings().frontend_base_url.rstrip("/")
    return (
        f"{base_url}/org/{approval.organization_id}/workspace/{approval.workspace_id}"
        f"/install/{approval.installation_id}?approvalId={approval.id}"
    )


def gateway_tool_approval_payload(
    approval: MCPGatewayToolApproval,
    *,
    include_result: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(approval.id),
        "status": approval.status,
        "serverName": approval.server_name,
        "toolName": approval.tool_name,
        "installationId": str(approval.installation_id),
        "toolSchemaId": str(approval.tool_schema_id) if approval.tool_schema_id else "",
        "approvalUrl": gateway_approval_url(approval),
        "createdAt": approval.created_at.isoformat() if approval.created_at else "",
        "updatedAt": approval.updated_at.isoformat() if approval.updated_at else "",
        "error": approval.error,
    }
    if include_result and approval.result is not None:
        payload["result"] = approval.result
    return payload


def gateway_tool_approval_read(
    approval: MCPGatewayToolApproval,
) -> MCPGatewayToolApprovalRead:
    return MCPGatewayToolApprovalRead(
        id=approval.id,
        organization_id=approval.organization_id,
        workspace_id=approval.workspace_id,
        requested_by_id=approval.requested_by_id,
        decided_by_id=approval.decided_by_id,
        installation_id=approval.installation_id,
        tool_schema_id=approval.tool_schema_id,
        tool_call_id=approval.tool_call_id,
        server_name=approval.server_name,
        tool_name=approval.tool_name,
        arguments=approval.arguments,
        request_meta=approval.request_meta,
        guardrail=approval.guardrail,
        status=approval.status,
        result=approval.result,
        error=approval.error,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def guardrail_tool_result(
    decision: GuardrailDecision,
    *,
    server_name: str,
    tool_name: str,
    approval: MCPGatewayToolApproval | None = None,
    guardrail_target: GatewayGuardrailTarget | None = None,
) -> dict[str, Any]:
    status = (
        "blocked"
        if decision.mode == GUARDRAIL_MODE_DENY
        else "approval_required"
    )
    message = decision.message or (
        "Tool call blocked by guardrail."
        if decision.mode == GUARDRAIL_MODE_DENY
        else "Tool call requires approval by guardrail."
    )
    if decision.mode == GUARDRAIL_MODE_DENY:
        message = (
            f"{message} Do not complete this denied MCP request from cached, prior, "
            "or alternate data."
        )
    return error_tool_result(
        message,
        {
            "serverName": server_name,
            "toolName": tool_name,
            "guardrail": {
                **guardrail_payload(decision, status=status, message=message),
                **(guardrail_target_payload(guardrail_target) if guardrail_target else {}),
                **(
                    {"approval": gateway_tool_approval_payload(approval)}
                    if approval is not None
                    else {}
                ),
            },
        },
    )


def gateway_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_mcp_servers",
            "title": "Search enabled MCP servers",
            "description": (
                "Search Wardn's enabled MCP servers. Use this first instead of listing every "
                "server; results are paginated and intentionally compact."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional search text matched against server name, title, "
                            "and description."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "default": 10,
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Cursor returned by a previous search_mcp_servers call.",
                    },
                },
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "servers": {"type": "array"},
                    "nextCursor": {"type": "string"},
                },
                "required": ["servers", "nextCursor"],
            },
        },
        {
            "name": "get_mcp_server",
            "title": "Get MCP server details",
            "description": (
                "Fetch detailed metadata for one enabled MCP server by canonical server name."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {
                        "type": "string",
                        "description": "Canonical MCP server name, for example namespace/server.",
                    },
                    "installationId": {
                        "type": "string",
                        "description": "Optional installation id when serverName is ambiguous.",
                    },
                },
                "required": ["serverName"],
            },
        },
        {
            "name": "search_mcp_tools",
            "title": "Search enabled MCP tools",
            "description": (
                "Search tools exposed by enabled MCP servers. Provide serverName after "
                "search_mcp_servers when possible; otherwise Wardn scans only a small "
                "bounded set of matching servers."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {
                        "type": "string",
                        "description": "Optional canonical MCP server name to search within.",
                    },
                    "installationId": {
                        "type": "string",
                        "description": "Optional installation id when serverName is ambiguous.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional search text matched against tool name, title, "
                            "and description."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "default": 10,
                    },
                },
            },
        },
        {
            "name": "get_mcp_tool",
            "title": "Get MCP tool details",
            "description": "Fetch the schema for one tool from one enabled MCP server.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {"type": "string"},
                    "installationId": {"type": "string"},
                    "toolName": {"type": "string"},
                },
                "required": ["serverName", "toolName"],
            },
        },
        {
            "name": "run_mcp_tool",
            "title": "Run MCP tool",
            "description": "Invoke one selected tool on one enabled MCP server.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {"type": "string"},
                    "installationId": {"type": "string"},
                    "toolName": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "description": "Tool arguments matching the tool input schema.",
                    },
                },
                "required": ["serverName", "toolName"],
            },
        },
        {
            "name": "get_mcp_tool_approval",
            "title": "Get MCP tool approval",
            "description": (
                "Check a gateway approval request created by run_mcp_tool. If the "
                "approval was completed in Wardn, returns the approved tool result."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "approvalId": {
                        "type": "string",
                        "description": "Approval ID returned by run_mcp_tool.",
                    },
                },
                "required": ["approvalId"],
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    ]


def parse_uuid_argument(value: Any, name: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid UUID") from exc


async def search_mcp_servers(
    session: AsyncSession,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
) -> dict[str, Any]:
    cursor = parse_cursor(arguments.get("cursor"))
    limit = bounded_limit(arguments.get("limit"))
    query = str(arguments.get("query") or "").strip()
    rows, next_cursor = await repository.search_enabled_installations(
        session,
        scope=scope,
        search=query,
        cursor=cursor,
        limit=limit,
    )
    return text_tool_result(
        {
            "servers": [
                server_summary(installation, server)
                for installation, server in rows
            ],
            "nextCursor": next_cursor,
        }
    )


async def get_mcp_server(
    session: AsyncSession,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
) -> dict[str, Any]:
    server_name = str(arguments.get("serverName") or "").strip()
    installation_id = parse_uuid_argument(arguments.get("installationId"), "installationId")
    if not server_name:
        raise ValueError("serverName is required")
    row = await repository.get_enabled_installation(
        session,
        server_name,
        scope=scope,
        installation_id=installation_id,
    )
    if row is None:
        raise LookupError("enabled MCP server was not found")
    installation, server = row
    return text_tool_result({"server": server_detail(installation, server)})


async def search_mcp_tools(
    session: AsyncSession,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
) -> dict[str, Any]:
    cursor = parse_cursor(arguments.get("cursor"))
    limit = bounded_limit(arguments.get("limit"))
    query = str(arguments.get("query") or "").strip()
    server_name = str(arguments.get("serverName") or "").strip()
    installation_id = parse_uuid_argument(arguments.get("installationId"), "installationId")
    refreshed = False

    if server_name:
        row = await repository.get_enabled_installation(
            session,
            server_name,
            scope=scope,
            installation_id=installation_id,
        )
        if row is None:
            raise LookupError("enabled MCP server was not found")
        installation, server = row
        tool_count = await tool_repository.count_active_tool_schemas(
            session,
            installation_id=installation.id,
            server_name=server.name,
            server_version=server.version,
        )
        if tool_count == 0:
            await refresh_tool_schemas(session, server_name, workspace_id=installation.workspace_id)
            refreshed = True

    tools, next_cursor = await tool_repository.search_enabled_tool_schemas(
        session,
        scope=scope,
        server_name=server_name,
        search=query,
        cursor=cursor,
        limit=limit,
    )

    return text_tool_result(
        {
            "tools": [cached_tool_summary(tool) for tool in tools],
            "nextCursor": next_cursor,
            "cache": {
                "mode": "cached-with-refresh" if refreshed else "cached",
                "refreshed": refreshed,
            },
        }
    )


async def get_mcp_tool(
    session: AsyncSession,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
) -> dict[str, Any]:
    server_name = str(arguments.get("serverName") or "").strip()
    tool_name = str(arguments.get("toolName") or "").strip()
    installation_id = parse_uuid_argument(arguments.get("installationId"), "installationId")
    if not server_name:
        raise ValueError("serverName is required")
    if not tool_name:
        raise ValueError("toolName is required")

    row = await repository.get_enabled_installation(
        session,
        server_name,
        scope=scope,
        installation_id=installation_id,
    )
    if row is None:
        raise LookupError("enabled MCP server was not found")
    installation, _server = row
    cached_tool = await tool_repository.get_enabled_tool_schema(
        session,
        scope=scope,
        installation_id=installation.id,
        server_name=server_name,
        tool_name=tool_name,
    )
    refreshed = False
    if cached_tool is None:
        await refresh_tool_schemas(session, server_name, workspace_id=installation.workspace_id)
        refreshed = True
        cached_tool = await tool_repository.get_enabled_tool_schema(
            session,
            scope=scope,
            installation_id=installation.id,
            server_name=server_name,
            tool_name=tool_name,
        )
    if cached_tool is not None:
        return text_tool_result(
            {
                "tool": cached_tool_summary(cached_tool),
                "cache": {
                    "mode": "cached-with-refresh" if refreshed else "cached",
                    "refreshed": refreshed,
                },
            }
        )
    raise LookupError("MCP tool was not found")


async def get_mcp_tool_approval(
    session: AsyncSession,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
) -> dict[str, Any]:
    approval_id = parse_uuid_argument(arguments.get("approvalId"), "approvalId")
    if approval_id is None:
        raise ValueError("approvalId is required")
    approval = await repository.get_gateway_tool_approval(
        session,
        approval_id,
        scope=scope,
    )
    if approval is None:
        raise LookupError("MCP tool approval was not found")
    payload: dict[str, Any] = {
        "approval": gateway_tool_approval_payload(approval, include_result=True),
    }
    if approval.result is not None:
        payload["approvedToolResult"] = approval.result
    if approval.status in {"failed", "denied"}:
        return error_tool_result(approval.error or f"Approval {approval.status}.", payload)
    return text_tool_result(payload)


async def run_mcp_tool(
    session: AsyncSession,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    server_name = str(arguments.get("serverName") or "").strip()
    tool_name = str(arguments.get("toolName") or "").strip()
    installation_id = parse_uuid_argument(arguments.get("installationId"), "installationId")
    tool_arguments = arguments.get("arguments")
    if not server_name:
        raise ValueError("serverName is required")
    if not tool_name:
        raise ValueError("toolName is required")
    if tool_arguments is None:
        tool_arguments = {}
    if not isinstance(tool_arguments, dict):
        raise ValueError("arguments must be an object")

    row = await repository.get_enabled_installation(
        session,
        server_name,
        scope=scope,
        installation_id=installation_id,
    )
    if row is None:
        raise LookupError("enabled MCP server was not found")
    installation, server = row
    guardrail_target = gateway_guardrail_target(tool_name, tool_arguments)
    decision = await evaluate_gateway_tool_guardrails(
        session,
        installation,
        server,
        tool_name=guardrail_target.tool_name,
        arguments=guardrail_target.arguments,
        scope=scope,
    )
    if decision.mode == GUARDRAIL_MODE_DENY:
        return guardrail_tool_result(
            decision,
            server_name=server_name,
            tool_name=tool_name,
            guardrail_target=guardrail_target,
        )
    if decision.mode == GUARDRAIL_MODE_REQUIRE_CONFIRMATION:
        workspace = await organizations_repository.get_workspace_by_id(
            session,
            installation.workspace_id,
        )
        if workspace is None:
            raise LookupError("workspace was not found for enabled MCP server")
        tool_schema = await tool_repository.get_enabled_tool_schema(
            session,
            scope=scope,
            installation_id=installation.id,
            server_name=installation.server_name,
            tool_name=guardrail_target.tool_name,
        )
        message = decision.message or "Tool call requires approval by guardrail."
        approval = await repository.create_gateway_tool_approval(
            session,
            organization_id=workspace.organization_id,
            workspace_id=installation.workspace_id,
            requested_by_id=scope.user_id,
            installation_id=installation.id,
            tool_schema_id=tool_schema.id if tool_schema else None,
            tool_call_id=str(uuid.uuid4()),
            server_name=server_name,
            tool_name=tool_name,
            arguments=tool_arguments,
            request_meta=request_meta or {},
            guardrail=guardrail_payload(
                decision,
                status="approval_required",
                message=message,
            )
            | guardrail_target_payload(guardrail_target),
        )
        return guardrail_tool_result(
            decision,
            server_name=server_name,
            tool_name=tool_name,
            approval=approval,
            guardrail_target=guardrail_target,
        )
    if decision.mode != GUARDRAIL_MODE_ALLOW:
        return error_tool_result(
            "Unsupported guardrail decision.",
            {
                "serverName": server_name,
                "toolName": tool_name,
                "guardrail": {
                    "status": "blocked",
                    "mode": decision.mode,
                },
            },
        )
    try:
        upstream_result = await call_tool_with_isolated_tracking(
            session,
            installation,
            server,
            tool_name=tool_name,
            arguments=tool_arguments,
            user_id=scope.user_id,
            request_meta=request_meta,
        )
        upstream_result = tool_result_with_structured_content(upstream_result)
    except (MCPGatewayUpstreamError, KubernetesRuntimeProviderError) as exc:
        return error_tool_result(
            str(exc),
            {
                "serverName": server_name,
                "toolName": tool_name,
                "error": str(exc),
            },
        )
    return {
        **upstream_result,
        "structuredContent": {
            "serverName": server_name,
            "toolName": tool_name,
            "upstreamResult": upstream_result,
        },
    }


async def list_gateway_tool_approvals(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    installation_id: uuid.UUID | None = None,
    status: str | None = "pending",
    limit: int = 25,
) -> MCPGatewayToolApprovalListResponse:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    approvals = await repository.list_gateway_tool_approvals(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        status=status,
        limit=min(max(limit, 1), 100),
    )
    return MCPGatewayToolApprovalListResponse(
        approvals=[gateway_tool_approval_read(approval) for approval in approvals]
    )


async def decide_gateway_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: MCPGatewayToolApprovalDecisionRequest,
) -> MCPGatewayToolApprovalDecisionResponse:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    approval = await repository.get_workspace_gateway_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise LookupError("MCP tool approval was not found")
    if approval.status != "pending":
        return MCPGatewayToolApprovalDecisionResponse(
            approval_id=approval.id,
            status=approval.status,
            tool_name=approval.tool_name,
            result=approval.result,
            error=approval.error,
        )

    approval.decided_by_id = user.id
    if payload.decision == "deny":
        approval.status = "denied"
        approval.error = "Denied by user."
        await session.flush()
        return MCPGatewayToolApprovalDecisionResponse(
            approval_id=approval.id,
            status=approval.status,
            tool_name=approval.tool_name,
            result=approval.result,
            error=approval.error,
        )

    approval.status = "running"
    await session.flush()
    row = await repository.get_enabled_installation(
        session,
        approval.server_name,
        scope=GatewayScope(
            user_id=user.id,
            is_superuser=user.is_superuser,
            organization_id=organization_id,
            workspace_id=workspace_id,
        ),
        installation_id=approval.installation_id,
    )
    if row is None:
        approval.status = "failed"
        approval.error = "Enabled MCP server was not found."
    else:
        installation, server = row
        try:
            result = await call_tool_with_isolated_tracking(
                session,
                installation,
                server,
                tool_name=approval.tool_name,
                arguments=approval.arguments,
                user_id=user.id,
                request_meta=approval.request_meta,
            )
            approval.result = tool_result_with_structured_content(result)
            approval.error = ""
            approval.status = "completed"
        except (MCPGatewayUpstreamError, KubernetesRuntimeProviderError) as exc:
            approval.status = "failed"
            approval.error = str(exc)
    await session.flush()
    return MCPGatewayToolApprovalDecisionResponse(
        approval_id=approval.id,
        status=approval.status,
        tool_name=approval.tool_name,
        result=approval.result,
        error=approval.error,
    )


async def evaluate_gateway_tool_guardrails(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    scope: GatewayScope,
) -> GuardrailDecision:
    workspace = await organizations_repository.get_workspace_by_id(
        session,
        installation.workspace_id,
    )
    if workspace is None:
        raise LookupError("workspace was not found for enabled MCP server")
    tool_schema = await tool_repository.get_enabled_tool_schema(
        session,
        scope=scope,
        installation_id=installation.id,
        server_name=installation.server_name,
        tool_name=tool_name,
    )
    return await evaluate_tool_call_guardrails(
        session,
        GuardrailEvaluationContext(
            organization_id=workspace.organization_id,
            workspace_id=installation.workspace_id,
            user_id=scope.user_id,
            agent_id=None,
            conversation_id=None,
            agent_run_id=None,
            installation_id=installation.id,
            tool_schema_id=tool_schema.id if tool_schema else None,
            server_name=server.name,
            tool_name=tool_name,
            arguments=arguments,
        ),
    )


def initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "wardn-mcp-gateway", "version": "0.1.0"},
    }


def ping_result() -> dict[str, Any]:
    return {}


async def call_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    scope: GatewayScope,
    request_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if name == "search_mcp_servers":
        return await search_mcp_servers(session, arguments, scope=scope)
    if name == "get_mcp_server":
        return await get_mcp_server(session, arguments, scope=scope)
    if name == "search_mcp_tools":
        return await search_mcp_tools(session, arguments, scope=scope)
    if name == "get_mcp_tool":
        return await get_mcp_tool(session, arguments, scope=scope)
    if name == "run_mcp_tool":
        return await run_mcp_tool(
            session,
            arguments,
            scope=scope,
            request_meta=request_meta,
        )
    if name == "get_mcp_tool_approval":
        return await get_mcp_tool_approval(session, arguments, scope=scope)
    raise LookupError(f"unknown gateway tool: {name}")
