import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app.core.outbound_http import UnsafeOutboundURLError, open_outbound_request
from app.modules.mcp_registry.exceptions import MCPServerInstallationFailedError
from app.modules.mcp_registry.installers.support import (
    ConfigValues,
    MCPRuntimeInstall,
    config_value_present,
    configured_values,
    custom_header_values,
    indexed_install_definition,
    named_fields,
    require_config_values,
    write_runtime_manifest,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import MCPServerVersion

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {PROTOCOL_VERSION, "2025-03-26", "2024-11-05", "2024-10-07"}
)

def parse_mcp_response_body(body: str) -> dict[str, Any]:
    body = body.strip()
    if not body:
        return {}
    if "data:" in body:
        fallback: dict[str, Any] = {}
        for line in body.splitlines():
            if line.startswith("data:"):
                data = line.removeprefix("data:").strip()
                if data and data != "[DONE]":
                    payload = json.loads(data)
                    if isinstance(payload, dict):
                        if "result" in payload or "error" in payload:
                            return payload
                        fallback = payload
        return fallback
    return json.loads(body)

def send_remote_mcp_request(
    url: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
    protocol_version: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "Wardn/0.1 MCP Registry Installer",
    }
    if extra_headers:
        headers.update(extra_headers)
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with open_outbound_request(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            return parse_mcp_response_body(body), response.headers.get("Mcp-Session-Id")
    except UnsafeOutboundURLError as exc:
        raise MCPServerInstallationFailedError(
            f"remote MCP server URL was rejected: {exc}"
        ) from exc
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        if detail:
            try:
                payload = json.loads(detail)
                detail = payload.get("detail") or payload.get("message") or detail
            except json.JSONDecodeError:
                pass
        raise MCPServerInstallationFailedError(
            f"remote MCP server returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise MCPServerInstallationFailedError(
            f"remote MCP server is not reachable: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MCPServerInstallationFailedError(
            "remote MCP server returned an invalid MCP response"
        ) from exc

def negotiated_protocol_version(response: dict[str, Any]) -> str:
    result = response.get("result")
    protocol_version = result.get("protocolVersion") if isinstance(result, dict) else None
    if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise MCPServerInstallationFailedError(
            f"remote MCP server negotiated unsupported protocol version: {protocol_version}"
        )
    return str(protocol_version)

def verify_remote_mcp_server(
    remote: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = str(remote.get("url") or "")
    if not url:
        raise MCPServerInstallationFailedError("remote MCP server URL is missing")

    initialize_response, session_id = send_remote_mcp_request(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "wardn", "version": "0.1.0"},
            },
        },
        extra_headers=extra_headers,
    )
    if "error" in initialize_response:
        raise MCPServerInstallationFailedError(
            f"remote MCP initialize failed: {initialize_response['error']}"
        )
    if "result" not in initialize_response:
        raise MCPServerInstallationFailedError("remote MCP initialize returned no result")
    protocol_version = negotiated_protocol_version(initialize_response)

    try:
        send_remote_mcp_request(
            url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id=session_id,
            extra_headers=extra_headers,
            protocol_version=protocol_version,
        )
    except MCPServerInstallationFailedError:
        # Some HTTP MCP servers return an empty/no-content response for notifications.
        # Continue to tools/list, which is the meaningful usability check.
        pass

    tools_response, _ = send_remote_mcp_request(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id=session_id,
        extra_headers=extra_headers,
        protocol_version=protocol_version,
    )
    if "error" in tools_response:
        raise MCPServerInstallationFailedError(
            f"remote MCP tools/list failed: {tools_response['error']}"
        )
    tools = tools_response.get("result", {}).get("tools")
    if not isinstance(tools, list):
        raise MCPServerInstallationFailedError("remote MCP tools/list returned no tools array")

    return {
        "protocolVersion": initialize_response.get("result", {}).get("protocolVersion", ""),
        "serverInfo": initialize_response.get("result", {}).get("serverInfo", {}),
        "toolCount": len(tools),
        "verifiedAt": datetime.now(UTC).isoformat(),
    }

def build_remote_install(
    server: MCPServerVersion,
    install_path: Path,
    config_values: ConfigValues,
    target_index: int = 0,
) -> MCPRuntimeInstall:
    remote = indexed_install_definition(server.remotes, target_index, label="remote")
    headers = remote.get("headers", []) if isinstance(remote.get("headers"), list) else []
    require_config_values(headers, config_values, label="connection settings")
    configured_headers = {
        **custom_header_values(config_values),
        **configured_values(headers, config_values),
    }
    verification = verify_remote_mcp_server(remote, extra_headers=configured_headers)
    public_remote = dict(remote)
    public_headers = [
        {
            **header,
            "configured": config_value_present(config_values.get(str(header.get("name") or ""))),
        }
        for header in headers
    ]
    custom_headers = custom_header_values(config_values)
    public_headers.extend(
        {
            "name": name,
            "isSecret": True,
            "isRequired": False,
            "configured": True,
            "custom": True,
        }
        for name in custom_headers
        if name not in named_fields(headers)
    )
    if public_headers:
        public_remote["headers"] = public_headers
    secret_config = {"headers": configured_headers} if configured_headers else {}
    runtime_config = {
        "kind": "remote",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "transport": public_remote,
        "requiresConfiguration": False,
        "verification": verification,
    }
    write_runtime_manifest(install_path, runtime_config)
    write_secret_manifest(install_path, secret_config)
    return MCPRuntimeInstall(
        install_type="remote",
        install_path=str(install_path),
        runtime_config=runtime_config,
        secret_config=secret_config,
        status="enabled",
    )

class RemoteInstaller:
    def install(
        self,
        server: MCPServerVersion,
        install_path: Path,
        config_values: ConfigValues,
        target_index: int = 0,
    ) -> MCPRuntimeInstall:
        return build_remote_install(server, install_path, config_values, target_index)

