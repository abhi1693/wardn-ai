from typing import Any

from app.modules.mcp_gateway import client
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_HEALTH_UNKNOWN,
    RUNTIME_KIND_REMOTE,
    RUNTIME_PROVIDER_REMOTE,
    RuntimeHealth,
    RuntimeSpec,
    base_runtime_spec,
    require_remote_installation,
    runtime_kind,
)


class RemoteRuntimeProvider:
    name = RUNTIME_PROVIDER_REMOTE

    def supports(self, installation: MCPServerInstallation) -> bool:
        return runtime_kind(installation) == RUNTIME_KIND_REMOTE

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        runtime = require_remote_installation(installation)
        return base_runtime_spec(
            installation,
            provider_name=self.name,
            transport=RUNTIME_KIND_REMOTE,
            endpoint_url=runtime.url,
        )

    def list_tools(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> list[dict[str, Any]]:
        runtime = require_remote_installation(installation)
        return client.list_tools(runtime.url, runtime.headers)

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        request_meta: dict[str, Any] | None = None,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        runtime = require_remote_installation(installation)
        return client.call_tool(
            runtime.url,
            runtime.headers,
            tool_name=tool_name,
            arguments=arguments,
            request_meta=request_meta,
        )

    def ensure_runtime(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
        wait_ready: bool = True,
    ) -> RuntimeHealth:
        return self.health(runtime_session) if runtime_session is not None else RuntimeHealth(
            status=RUNTIME_HEALTH_UNKNOWN,
            healthy=True,
            ready=True,
            message="Remote runtime is externally hosted.",
        )

    def stop_runtime(
        self,
        runtime_session: MCPRuntimeSession,
        *,
        delete_resources: bool = False,
    ) -> None:
        return None

    def health(self, runtime_session: MCPRuntimeSession) -> RuntimeHealth:
        return RuntimeHealth(
            status=RUNTIME_HEALTH_UNKNOWN,
            healthy=True,
            ready=True,
            message="Remote runtime is externally hosted; no local readiness probe is available.",
            details={"endpointConfigured": bool(runtime_session.endpoint_url)},
        )
