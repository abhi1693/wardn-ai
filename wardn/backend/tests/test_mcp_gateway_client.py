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
