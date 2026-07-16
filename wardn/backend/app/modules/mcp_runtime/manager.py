import shutil
from threading import Event
from typing import Any, Protocol

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_KIND_PACKAGE,
    RUNTIME_KIND_REMOTE,
    RUNTIME_PROVIDER_AUTO,
    RUNTIME_PROVIDER_KUBERNETES,
    RUNTIME_PROVIDER_LOCAL,
    RUNTIME_PROVIDER_REMOTE,
    RUNTIME_TRANSPORT_STDIO,
    RUNTIME_TRANSPORT_STREAMABLE_HTTP,
    WARDN_CUSTOM_HEADERS_ENV,
    MCPProgressCallback,
    MCPRuntimeProvider,
    RuntimeHealth,
    RuntimeSpec,
    normalize_installed_path,
    package_runtime,
    remote_url,
    require_remote_installation,
    runtime_kind,
    secret_environment,
    secret_headers,
)
from app.modules.mcp_runtime.providers import (
    KubernetesRuntimeProvider,
    LocalProcessRuntimeProvider,
    RemoteRuntimeProvider,
)


class MCPRuntimeManager(Protocol):
    def provider_name(self, installation: MCPServerInstallation) -> str:
        ...

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        ...

    def runtime_fingerprint(self, installation: MCPServerInstallation) -> str:
        ...

    def list_tools(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        cancel_event: Event | None = None,
        cancel_reason: str = "Tool call cancelled.",
        request_meta: dict[str, Any] | None = None,
        progress_callback: MCPProgressCallback | None = None,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        ...

    def ensure_runtime(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
        wait_ready: bool = True,
    ) -> RuntimeHealth:
        ...

    def stop_runtime(
        self,
        runtime_session: MCPRuntimeSession,
        *,
        delete_resources: bool = False,
    ) -> None:
        ...

    def health_runtime(self, runtime_session: MCPRuntimeSession) -> RuntimeHealth:
        ...

    def shutdown_local_runtimes(self) -> None:
        ...


class RuntimeProviderRegistry:
    def __init__(self, providers: list[MCPRuntimeProvider]) -> None:
        self._providers = {provider.name: provider for provider in providers}

    def select_provider(self, installation: MCPServerInstallation) -> MCPRuntimeProvider:
        kind = runtime_kind(installation)
        if kind == RUNTIME_KIND_REMOTE:
            return self._provider(RUNTIME_PROVIDER_REMOTE, installation)

        configured_provider = get_settings().mcp_runtime_provider.lower()
        if kind == RUNTIME_KIND_PACKAGE:
            if configured_provider in (RUNTIME_PROVIDER_AUTO, RUNTIME_PROVIDER_LOCAL):
                return self._provider(RUNTIME_PROVIDER_LOCAL, installation)
            if configured_provider == RUNTIME_PROVIDER_KUBERNETES:
                return self._provider(RUNTIME_PROVIDER_KUBERNETES, installation)
            return self._provider(configured_provider, installation)

        raise ValueError(f"MCP server runtime is not supported yet: {kind}")

    def _provider(
        self,
        name: str,
        installation: MCPServerInstallation,
    ) -> MCPRuntimeProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ValueError(f"MCP runtime provider is not registered: {name}")
        if not provider.supports(installation):
            kind = runtime_kind(installation)
            raise ValueError(f"MCP runtime provider {name!r} does not support runtime {kind!r}")
        return provider

    def provider_by_name(self, name: str) -> MCPRuntimeProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ValueError(f"MCP runtime provider is not registered: {name}")
        return provider


class DefaultMCPRuntimeManager:
    def __init__(self, registry: RuntimeProviderRegistry | None = None) -> None:
        self._registry = registry or RuntimeProviderRegistry(
            [
                RemoteRuntimeProvider(),
                LocalProcessRuntimeProvider(),
                KubernetesRuntimeProvider(),
            ]
        )

    def provider_name(self, installation: MCPServerInstallation) -> str:
        return self._registry.select_provider(installation).name

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        return self._registry.select_provider(installation).runtime_spec(installation)

    def runtime_fingerprint(self, installation: MCPServerInstallation) -> str:
        return self.runtime_spec(installation).fingerprint()

    def list_tools(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> list[dict[str, Any]]:
        return self._registry.select_provider(installation).list_tools(
            installation,
            runtime_session=runtime_session,
        )

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        cancel_event: Event | None = None,
        cancel_reason: str = "Tool call cancelled.",
        request_meta: dict[str, Any] | None = None,
        progress_callback: MCPProgressCallback | None = None,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        return self._registry.select_provider(installation).call_tool(
            installation,
            tool_name=tool_name,
            arguments=arguments,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            request_meta=request_meta,
            progress_callback=progress_callback,
            runtime_session=runtime_session,
        )

    def ensure_runtime(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
        wait_ready: bool = True,
    ) -> RuntimeHealth:
        return self._registry.select_provider(installation).ensure_runtime(
            installation,
            runtime_session=runtime_session,
            wait_ready=wait_ready,
        )

    def stop_runtime(
        self,
        runtime_session: MCPRuntimeSession,
        *,
        delete_resources: bool = False,
    ) -> None:
        self._registry.provider_by_name(runtime_session.runtime_provider).stop_runtime(
            runtime_session,
            delete_resources=delete_resources,
        )

    def health_runtime(self, runtime_session: MCPRuntimeSession) -> RuntimeHealth:
        return self._registry.provider_by_name(runtime_session.runtime_provider).health(
            runtime_session
        )

    def shutdown_local_runtimes(self) -> None:
        provider = self._registry.provider_by_name(RUNTIME_PROVIDER_LOCAL)
        stop_all = getattr(provider, "stop_all", None)
        if stop_all is not None:
            stop_all()


def get_runtime_manager() -> MCPRuntimeManager:
    return _DEFAULT_RUNTIME_MANAGER


_DEFAULT_RUNTIME_MANAGER = DefaultMCPRuntimeManager()

__all__ = [
    "DefaultMCPRuntimeManager",
    "MCPRuntimeManager",
    "MCPRuntimeProvider",
    "RUNTIME_KIND_PACKAGE",
    "RUNTIME_KIND_REMOTE",
    "RUNTIME_PROVIDER_AUTO",
    "RUNTIME_PROVIDER_KUBERNETES",
    "RUNTIME_PROVIDER_LOCAL",
    "RUNTIME_PROVIDER_REMOTE",
    "RUNTIME_TRANSPORT_STREAMABLE_HTTP",
    "RUNTIME_TRANSPORT_STDIO",
    "RuntimeProviderRegistry",
    "RuntimeHealth",
    "RuntimeSpec",
    "WARDN_CUSTOM_HEADERS_ENV",
    "get_runtime_manager",
    "normalize_installed_path",
    "package_runtime",
    "remote_url",
    "require_remote_installation",
    "runtime_kind",
    "secret_environment",
    "secret_headers",
    "shutil",
]
