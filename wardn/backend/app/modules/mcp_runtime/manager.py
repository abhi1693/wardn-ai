import shutil
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
    WARDN_CUSTOM_HEADERS_ENV,
    MCPRuntimeProvider,
    RuntimeSpec,
    normalize_installed_path,
    package_runtime,
    remote_url,
    require_remote_installation,
    runtime_kind,
    secret_environment,
    secret_headers,
)
from app.modules.mcp_runtime.providers import LocalProcessRuntimeProvider, RemoteRuntimeProvider


class MCPRuntimeManager(Protocol):
    def provider_name(self, installation: MCPServerInstallation) -> str:
        ...

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        ...

    def runtime_fingerprint(self, installation: MCPServerInstallation) -> str:
        ...

    def list_tools(self, installation: MCPServerInstallation) -> list[dict[str, Any]]:
        ...

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        ...

    def stop_runtime(self, runtime_session: MCPRuntimeSession) -> None:
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
                raise ValueError(
                    "kubernetes MCP runtime provider is not implemented yet; "
                    "set WARDN_MCP_RUNTIME_PROVIDER=local for package servers"
                )
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
            ]
        )

    def provider_name(self, installation: MCPServerInstallation) -> str:
        return self._registry.select_provider(installation).name

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        return self._registry.select_provider(installation).runtime_spec(installation)

    def runtime_fingerprint(self, installation: MCPServerInstallation) -> str:
        return self.runtime_spec(installation).fingerprint()

    def list_tools(self, installation: MCPServerInstallation) -> list[dict[str, Any]]:
        return self._registry.select_provider(installation).list_tools(installation)

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        return self._registry.select_provider(installation).call_tool(
            installation,
            tool_name=tool_name,
            arguments=arguments,
            runtime_session=runtime_session,
        )

    def stop_runtime(self, runtime_session: MCPRuntimeSession) -> None:
        self._registry.provider_by_name(runtime_session.runtime_provider).stop_runtime(
            runtime_session
        )


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
    "RUNTIME_TRANSPORT_STDIO",
    "RuntimeProviderRegistry",
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
