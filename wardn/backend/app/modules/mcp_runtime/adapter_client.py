import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.mcp_registry.installer import parse_mcp_response_body
from app.modules.mcp_runtime.adapter_contract import (
    ADAPTER_MCP_PATH,
    ADAPTER_READY_PATH,
    adapter_url,
)


class MCPRuntimeAdapterError(Exception):
    pass


def send_adapter_request(
    endpoint_url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30,
) -> dict[str, Any]:
    request = Request(
        adapter_url(endpoint_url, ADAPTER_MCP_PATH),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Wardn/0.1 Runtime Adapter Client",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            if not body:
                return {}
            return parse_mcp_response_body(body)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise MCPRuntimeAdapterError(
            f"runtime adapter returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise MCPRuntimeAdapterError(f"runtime adapter is not reachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MCPRuntimeAdapterError("runtime adapter returned invalid JSON-RPC") from exc


def get_adapter_status(
    endpoint_url: str,
    *,
    timeout: float = 5,
) -> dict[str, Any]:
    request = Request(
        adapter_url(endpoint_url, ADAPTER_READY_PATH),
        headers={
            "Accept": "application/json",
            "User-Agent": "Wardn/0.1 Runtime Adapter Client",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise MCPRuntimeAdapterError(
            f"runtime adapter returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise MCPRuntimeAdapterError(f"runtime adapter is not reachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MCPRuntimeAdapterError("runtime adapter returned invalid status JSON") from exc


def list_tools(
    endpoint_url: str,
    *,
    request_id_start: int = 2,
    max_pages: int = 100,
) -> tuple[list[dict[str, Any]], int]:
    tools: list[dict[str, Any]] = []
    cursor = None
    next_request_id = request_id_start
    for request_id in range(request_id_start, request_id_start + max_pages):
        next_request_id = request_id + 1
        params = {"cursor": cursor} if cursor else {}
        response = send_adapter_request(
            endpoint_url,
            {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": params},
        )
        if "error" in response:
            raise MCPRuntimeAdapterError(f"runtime adapter tools/list failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise MCPRuntimeAdapterError("runtime adapter tools/list returned no tools array")
        tools.extend(item for item in result["tools"] if isinstance(item, dict))
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return tools, next_request_id


def call_tool(
    endpoint_url: str,
    *,
    request_id: int,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = send_adapter_request(
        endpoint_url,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    )
    if "error" in response:
        raise MCPRuntimeAdapterError(f"runtime adapter tools/call failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise MCPRuntimeAdapterError("runtime adapter tools/call returned no result")
    return result
