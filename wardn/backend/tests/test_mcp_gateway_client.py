import sys
from threading import Event

import pytest

from app.core.outbound_http import UnsafeOutboundURLError
from app.modules.mcp_gateway.client import (
    MCPGatewayUpstreamError,
    call_stdio_tool,
    list_stdio_tools,
    send_remote_request,
    stdio_process_environment,
)


def test_list_stdio_tools_includes_stderr_when_process_exits() -> None:
    with pytest.raises(MCPGatewayUpstreamError) as exc_info:
        list_stdio_tools(
            sys.executable,
            ["-c", "import sys; sys.stderr.write('missing PROMETHEUS_URL\\n'); sys.exit(2)"],
            cwd="",
            environment={},
        )

    assert "stdio MCP process exited before response 1" in str(exc_info.value)
    assert "missing PROMETHEUS_URL" in str(exc_info.value)


def test_list_stdio_tools_answers_server_ping_while_waiting_for_response() -> None:
    script = r"""
import json
import sys

initialize = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": "server-ping", "method": "ping"}), flush=True)
ping_response = json.loads(sys.stdin.readline())
if ping_response != {"jsonrpc": "2.0", "id": "server-ping", "result": {}}:
    sys.stderr.write(f"unexpected ping response: {ping_response}\n")
    sys.exit(2)
print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": initialize["id"],
            "result": {"protocolVersion": "2025-06-18"},
        }
    ),
    flush=True,
)
sys.stdin.readline()
tools_request = json.loads(sys.stdin.readline())
print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": tools_request["id"],
            "result": {"tools": [{"name": "health", "inputSchema": {"type": "object"}}]},
        }
    ),
    flush=True,
)
"""

    tools = list_stdio_tools(sys.executable, ["-c", script], cwd="", environment={})

    assert tools == [{"name": "health", "inputSchema": {"type": "object"}}]


def test_call_stdio_tool_sends_progress_token_and_ignores_progress_notification() -> None:
    script = r"""
import json
import sys

initialize = json.loads(sys.stdin.readline())
print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": initialize["id"],
            "result": {"protocolVersion": "2025-06-18"},
        }
    ),
    flush=True,
)
sys.stdin.readline()
tool_request = json.loads(sys.stdin.readline())
if tool_request["params"].get("_meta") != {"progressToken": 123}:
    sys.stderr.write(f"unexpected request meta: {tool_request}\n")
    sys.exit(2)
print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progressToken": 123, "progress": 1, "total": 2},
        }
    ),
    flush=True,
)
print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": tool_request["id"],
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    ),
    flush=True,
)
"""

    progress_updates = []

    result = call_stdio_tool(
        sys.executable,
        ["-c", script],
        cwd="",
        environment={},
        tool_name="health",
        arguments={},
        request_meta={"progressToken": 123},
        progress_callback=progress_updates.append,
    )

    assert result == {"content": [{"type": "text", "text": "ok"}], "isError": False}
    assert progress_updates == [{"progressToken": 123, "progress": 1, "total": 2}]


def test_call_stdio_tool_sends_cancelled_notification_when_cancelled() -> None:
    script = r"""
import json
import sys

initialize = json.loads(sys.stdin.readline())
print(
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": initialize["id"],
            "result": {"protocolVersion": "2025-06-18"},
        }
    ),
    flush=True,
)
sys.stdin.readline()
tool_request = json.loads(sys.stdin.readline())
cancel_notification = json.loads(sys.stdin.readline())
expected = {
    "jsonrpc": "2.0",
    "method": "notifications/cancelled",
    "params": {"requestId": tool_request["id"], "reason": "user stopped chat"},
}
if cancel_notification != expected:
    sys.stderr.write(f"unexpected cancellation: {cancel_notification}\n")
    sys.exit(2)
"""
    cancel_event = Event()
    cancel_event.set()

    with pytest.raises(MCPGatewayUpstreamError, match="cancelled"):
        call_stdio_tool(
            sys.executable,
            ["-c", script],
            cwd="",
            environment={},
            tool_name="health",
            arguments={},
            cancel_event=cancel_event,
            cancel_reason="user stopped chat",
        )


def test_send_remote_request_adds_protocol_version_header(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"jsonrpc":"2.0","id":2,"result":{}}'

    def open_outbound_request(request, *args, **kwargs):
        seen["headers"] = {key.lower(): value for key, value in request.header_items()}
        return FakeResponse()

    monkeypatch.setattr(
        "app.modules.mcp_gateway.client.open_outbound_request",
        open_outbound_request,
    )

    send_remote_request(
        "https://example.com/mcp",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        protocol_version="2025-06-18",
    )

    assert seen["headers"]["mcp-protocol-version"] == "2025-06-18"


def test_send_remote_request_maps_rejected_url_to_gateway_error(monkeypatch) -> None:
    def reject_url(*args, **kwargs):
        raise UnsafeOutboundURLError("outbound URL resolves to a non-public address")

    monkeypatch.setattr(
        "app.modules.mcp_gateway.client.open_outbound_request",
        reject_url,
    )

    with pytest.raises(MCPGatewayUpstreamError, match="MCP URL was rejected"):
        send_remote_request(
            "http://169.254.169.254/latest/meta-data",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )


def test_stdio_process_environment_only_inherits_allowlisted_values() -> None:
    environment = stdio_process_environment(
        {"MCP_API_KEY": "explicit-secret", "PATH": "/custom/bin"},
        ambient_environment={
            "HOME": "/home/wardn",
            "LANG": "C.UTF-8",
            "PATH": "/usr/bin",
            "WARDN_DATABASE_URL": "database-secret",
            "WARDN_SESSION_SECRET": "session-secret",
            "KUBERNETES_SERVICE_HOST": "10.0.0.1",
            "HTTPS_PROXY": "https://user:password@proxy.example",
        },
    )

    assert environment == {
        "HOME": "/home/wardn",
        "LANG": "C.UTF-8",
        "PATH": "/custom/bin",
        "MCP_API_KEY": "explicit-secret",
    }
