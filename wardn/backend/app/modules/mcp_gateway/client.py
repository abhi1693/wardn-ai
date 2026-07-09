import json
import os
import select
import ssl
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.modules.mcp_registry.installer import parse_mcp_response_body

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {PROTOCOL_VERSION, "2025-03-26", "2024-11-05", "2024-10-07"}
)


class MCPGatewayUpstreamError(Exception):
    pass


@dataclass(frozen=True)
class MCPRemoteSession:
    url: str
    headers: dict[str, str]
    session_id: str | None
    protocol_version: str


@dataclass(frozen=True)
class MCPStdioSession:
    process: subprocess.Popen[str]


MCPProgressCallback = Callable[[dict[str, Any]], None]


def send_remote_request(
    url: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    headers: dict[str, str] | None = None,
    protocol_version: str | None = None,
    verify_tls: bool = True,
) -> tuple[dict[str, Any], str | None]:
    request_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "Wardn/0.1 MCP Gateway",
    }
    if headers:
        request_headers.update(headers)
    if session_id:
        request_headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        request_headers["MCP-Protocol-Version"] = protocol_version

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        context = None if verify_tls else ssl._create_unverified_context()
        with urlopen(request, timeout=30, context=context) as response:
            body = response.read().decode("utf-8", "replace")
            return parse_mcp_response_body(body), response.headers.get("Mcp-Session-Id")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        if detail:
            try:
                parsed = parse_mcp_response_body(detail)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and (
                "result" in parsed or "error" in parsed
            ):
                return parsed, exc.headers.get("Mcp-Session-Id")
        raise MCPGatewayUpstreamError(
            f"upstream MCP server returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise MCPGatewayUpstreamError(f"upstream MCP server is not reachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MCPGatewayUpstreamError("upstream MCP server returned invalid JSON-RPC") from exc


def negotiated_protocol_version(response: dict[str, Any]) -> str:
    result = response.get("result")
    protocol_version = result.get("protocolVersion") if isinstance(result, dict) else None
    if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise MCPGatewayUpstreamError(
            f"upstream MCP server negotiated unsupported protocol version: {protocol_version}"
        )
    return str(protocol_version)


def open_remote_session(
    url: str,
    headers: dict[str, str],
    *,
    verify_tls: bool = True,
) -> MCPRemoteSession:
    response, session_id = send_remote_request(
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
        headers=headers,
        verify_tls=verify_tls,
    )
    if "error" in response:
        raise MCPGatewayUpstreamError(f"upstream initialize failed: {response['error']}")
    if "result" not in response:
        raise MCPGatewayUpstreamError("upstream initialize returned no result")
    protocol_version = negotiated_protocol_version(response)

    try:
        send_remote_request(
            url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id=session_id,
            headers=headers,
            protocol_version=protocol_version,
            verify_tls=verify_tls,
        )
    except MCPGatewayUpstreamError:
        pass

    return MCPRemoteSession(
        url=url,
        headers=headers,
        session_id=session_id,
        protocol_version=protocol_version,
    )


def start_stdio_session(
    command: str,
    args: list[str],
    *,
    cwd: str,
    environment: dict[str, str],
) -> MCPStdioSession:
    env = {**os.environ, **environment}
    try:
        process = subprocess.Popen(
            [command, *args],
            cwd=cwd or None,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise MCPGatewayUpstreamError(f"stdio MCP command was not found: {command}") from exc
    except OSError as exc:
        raise MCPGatewayUpstreamError(f"stdio MCP command could not start: {exc}") from exc
    return MCPStdioSession(process=process)


def stderr_tail(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    try:
        stderr = process.stderr.read()
    except OSError:
        return ""
    return stderr.strip()[-1000:]


def close_stdio_session(session: MCPStdioSession) -> None:
    process = session.process
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def send_stdio_message(session: MCPStdioSession, payload: dict[str, Any]) -> None:
    if session.process.stdin is None:
        raise MCPGatewayUpstreamError("stdio MCP process has no stdin")
    try:
        session.process.stdin.write(f"{json.dumps(payload)}\n")
        session.process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise MCPGatewayUpstreamError("stdio MCP process closed stdin") from exc


def send_stdio_cancelled(
    session: MCPStdioSession,
    request_id: int,
    *,
    reason: str = "Request cancelled.",
) -> None:
    send_stdio_message(
        session,
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": request_id,
                "reason": reason,
            },
        },
    )


def handle_stdio_peer_request(session: MCPStdioSession, payload: dict[str, Any]) -> bool:
    if payload.get("jsonrpc") != "2.0" or payload.get("method") != "ping" or "id" not in payload:
        return False
    send_stdio_message(
        session,
        {"jsonrpc": "2.0", "id": payload.get("id"), "result": {}},
    )
    return True


def progress_notification_params(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("jsonrpc") != "2.0" or payload.get("method") != "notifications/progress":
        return None
    params = payload.get("params")
    return params if isinstance(params, dict) else {}


def is_stdio_peer_notification(payload: dict[str, Any]) -> bool:
    method = payload.get("method")
    return payload.get("jsonrpc") == "2.0" and isinstance(method, str) and method.startswith(
        "notifications/"
    )


def read_stdio_response(
    session: MCPStdioSession,
    request_id: int,
    *,
    cancel_event: Event | None = None,
    cancel_reason: str = "Request cancelled.",
    progress_callback: MCPProgressCallback | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    process = session.process
    if process.stdout is None:
        raise MCPGatewayUpstreamError("stdio MCP process has no stdout")

    if timeout is None:
        timeout = get_settings().mcp_gateway_stdio_response_timeout_seconds
    deadline = time.monotonic() + timeout
    cancellation_sent = False
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            if not cancellation_sent:
                send_stdio_cancelled(session, request_id, reason=cancel_reason)
                cancellation_sent = True
            raise MCPGatewayUpstreamError("stdio MCP request was cancelled")
        if process.poll() is not None:
            detail = stderr_tail(process)
            suffix = f": {detail}" if detail else ""
            raise MCPGatewayUpstreamError(
                f"stdio MCP process exited before response {request_id}{suffix}"
            )
        remaining = max(0.1, min(0.25, deadline - time.monotonic()))
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if handle_stdio_peer_request(session, response):
            continue
        if progress_params := progress_notification_params(response):
            if progress_callback is not None:
                progress_callback(progress_params)
            continue
        if is_stdio_peer_notification(response):
            continue
        if response.get("id") == request_id:
            return response
    raise MCPGatewayUpstreamError(f"stdio MCP process timed out waiting for {request_id}")


def open_stdio_session(
    command: str,
    args: list[str],
    *,
    cwd: str,
    environment: dict[str, str],
) -> MCPStdioSession:
    session = start_stdio_session(command, args, cwd=cwd, environment=environment)
    try:
        send_stdio_message(
            session,
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
        )
        response = read_stdio_response(session, 1)
        if "error" in response:
            raise MCPGatewayUpstreamError(f"upstream initialize failed: {response['error']}")
        if "result" not in response:
            raise MCPGatewayUpstreamError("upstream initialize returned no result")
        negotiated_protocol_version(response)
        send_stdio_message(
            session,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        return session
    except Exception:
        close_stdio_session(session)
        raise


def list_tools(
    url: str,
    headers: dict[str, str],
    *,
    max_pages: int = 100,
    verify_tls: bool = True,
) -> list[dict[str, Any]]:
    session = open_remote_session(url, headers, verify_tls=verify_tls)
    tools: list[dict[str, Any]] = []
    cursor = None
    for request_id in range(2, max_pages + 2):
        params = {"cursor": cursor} if cursor else {}
        response, _ = send_remote_request(
            session.url,
            {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": params},
            session_id=session.session_id,
            headers=session.headers,
            protocol_version=session.protocol_version,
            verify_tls=verify_tls,
        )
        if "error" in response:
            raise MCPGatewayUpstreamError(f"upstream tools/list failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise MCPGatewayUpstreamError("upstream tools/list returned no tools array")
        tools.extend(item for item in result["tools"] if isinstance(item, dict))
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return tools


def list_stdio_tools(
    command: str,
    args: list[str],
    *,
    cwd: str,
    environment: dict[str, str],
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    session = open_stdio_session(command, args, cwd=cwd, environment=environment)
    try:
        tools: list[dict[str, Any]] = []
        cursor = None
        for request_id in range(2, max_pages + 2):
            params = {"cursor": cursor} if cursor else {}
            send_stdio_message(
                session,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/list",
                    "params": params,
                },
            )
            response = read_stdio_response(session, request_id)
            if "error" in response:
                raise MCPGatewayUpstreamError(f"upstream tools/list failed: {response['error']}")
            result = response.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise MCPGatewayUpstreamError("upstream tools/list returned no tools array")
            tools.extend(item for item in result["tools"] if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools
    finally:
        close_stdio_session(session)


def list_stdio_session_tools(
    session: MCPStdioSession,
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
        send_stdio_message(
            session,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/list",
                "params": params,
            },
        )
        response = read_stdio_response(session, request_id)
        if "error" in response:
            raise MCPGatewayUpstreamError(f"upstream tools/list failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise MCPGatewayUpstreamError("upstream tools/list returned no tools array")
        tools.extend(item for item in result["tools"] if isinstance(item, dict))
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return tools, next_request_id


def call_tool(
    url: str,
    headers: dict[str, str],
    *,
    tool_name: str,
    arguments: dict[str, Any],
    request_meta: dict[str, Any] | None = None,
    verify_tls: bool = True,
) -> dict[str, Any]:
    session = open_remote_session(url, headers, verify_tls=verify_tls)
    params: dict[str, Any] = {"name": tool_name, "arguments": arguments}
    if request_meta:
        params["_meta"] = request_meta
    response, _ = send_remote_request(
        session.url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": params,
        },
        session_id=session.session_id,
        headers=session.headers,
        protocol_version=session.protocol_version,
        verify_tls=verify_tls,
    )
    if "error" in response:
        raise MCPGatewayUpstreamError(f"upstream tools/call failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise MCPGatewayUpstreamError("upstream tools/call returned no result")
    return result


def call_stdio_session_tool(
    session: MCPStdioSession,
    *,
    request_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    cancel_event: Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    request_meta: dict[str, Any] | None = None,
    progress_callback: MCPProgressCallback | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": tool_name, "arguments": arguments}
    if request_meta:
        params["_meta"] = request_meta
    send_stdio_message(
        session,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": params,
        },
    )
    response = read_stdio_response(
        session,
        request_id,
        cancel_event=cancel_event,
        cancel_reason=cancel_reason,
        progress_callback=progress_callback,
    )
    if "error" in response:
        raise MCPGatewayUpstreamError(f"upstream tools/call failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise MCPGatewayUpstreamError("upstream tools/call returned no result")
    return result


def call_stdio_tool(
    command: str,
    args: list[str],
    *,
    cwd: str,
    environment: dict[str, str],
    tool_name: str,
    arguments: dict[str, Any],
    cancel_event: Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    request_meta: dict[str, Any] | None = None,
    progress_callback: MCPProgressCallback | None = None,
) -> dict[str, Any]:
    session = open_stdio_session(command, args, cwd=cwd, environment=environment)
    try:
        return call_stdio_session_tool(
            session,
            request_id=2,
            tool_name=tool_name,
            arguments=arguments,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            request_meta=request_meta,
            progress_callback=progress_callback,
        )
    finally:
        close_stdio_session(session)
