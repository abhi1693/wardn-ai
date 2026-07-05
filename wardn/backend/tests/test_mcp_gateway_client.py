import sys

import pytest

from app.modules.mcp_gateway.client import MCPGatewayUpstreamError, list_stdio_tools


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
print(json.dumps({"jsonrpc": "2.0", "id": initialize["id"], "result": {}}), flush=True)
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
