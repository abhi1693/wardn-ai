import json
import shutil
from pathlib import Path
from typing import Any, Protocol

from app.modules.mcp_gateway import client
from app.modules.mcp_registry.models import MCPServerInstallation


class MCPRuntimeManager(Protocol):
    def provider_name(self, installation: MCPServerInstallation) -> str:
        ...

    def list_tools(self, installation: MCPServerInstallation) -> list[dict[str, Any]]:
        ...

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        ...


def runtime_kind(installation: MCPServerInstallation) -> str:
    runtime_config = installation.runtime_config or {}
    return str(runtime_config.get("kind") or installation.install_type)


def remote_url(installation: MCPServerInstallation) -> str:
    runtime_config = installation.runtime_config or {}
    transport = runtime_config.get("transport")
    if not isinstance(transport, dict):
        return ""
    return str(transport.get("url") or "")


def secret_headers(installation: MCPServerInstallation) -> dict[str, str]:
    secret_config = installation.secret_config or {}
    headers = secret_config.get("headers")
    if not isinstance(headers, dict):
        return {}
    return {str(key): str(value) for key, value in headers.items() if value is not None}


def secret_environment(installation: MCPServerInstallation) -> dict[str, str]:
    secret_config = installation.secret_config or {}
    environment = secret_config.get("environment")
    values = {}
    if isinstance(environment, dict):
        values.update(
            {str(key): str(value) for key, value in environment.items() if value is not None}
        )

    headers = secret_headers(installation)
    if headers:
        values["WARDN_MCP_CUSTOM_HEADERS"] = json.dumps(
            headers,
            separators=(",", ":"),
            sort_keys=True,
        )
    return values


def require_remote_installation(installation: MCPServerInstallation) -> tuple[str, dict[str, str]]:
    if runtime_kind(installation) != "remote":
        raise ValueError("installation is not a remote MCP server")
    url = remote_url(installation)
    if not url:
        raise ValueError("remote MCP server URL is missing from installation runtime")
    return url, secret_headers(installation)


def normalize_installed_path(value: Any, installation: MCPServerInstallation) -> Any:
    install_path = installation.install_path or str(
        (installation.runtime_config or {}).get("installPath") or ""
    )
    if not install_path or not isinstance(value, str):
        return value
    tmp_path = f"{install_path}.tmp"
    if value.startswith(tmp_path):
        return f"{install_path}{value[len(tmp_path):]}"
    return value


def package_runtime(
    installation: MCPServerInstallation,
) -> tuple[str, list[str], str, dict[str, str]]:
    if runtime_kind(installation) != "package":
        raise ValueError("installation is not a package MCP server")

    runtime_config = installation.runtime_config or {}
    transport = runtime_config.get("transport")
    if isinstance(transport, dict) and transport.get("type") not in (None, "stdio"):
        raise ValueError("only stdio package MCP server transports can be proxied right now")

    command = str(normalize_installed_path(runtime_config.get("command") or "", installation))
    if not command:
        raise ValueError("package MCP server command is missing from installation runtime")

    raw_args = runtime_config.get("args")
    args = [str(normalize_installed_path(arg, installation)) for arg in raw_args or []]
    raw_cwd = runtime_config.get("cwd") or installation.install_path
    cwd = str(normalize_installed_path(raw_cwd, installation))
    if command and ("/" in command or "\\" in command) and not Path(command).exists():
        raise ValueError(f"package MCP server command does not exist: {command}")
    if command and "/" not in command and "\\" not in command and shutil.which(command) is None:
        raise ValueError(f"package MCP server command was not found in PATH: {command}")
    if cwd and not Path(cwd).exists():
        raise ValueError(f"package MCP server working directory does not exist: {cwd}")
    return command, args, cwd, secret_environment(installation)


class DefaultMCPRuntimeManager:
    def provider_name(self, installation: MCPServerInstallation) -> str:
        kind = runtime_kind(installation)
        if kind == "remote":
            return "remote"
        if kind == "package":
            return "local"
        return kind

    def list_tools(self, installation: MCPServerInstallation) -> list[dict[str, Any]]:
        kind = runtime_kind(installation)
        if kind == "remote":
            url, headers = require_remote_installation(installation)
            return client.list_tools(url, headers)
        if kind == "package":
            command, args, cwd, environment = package_runtime(installation)
            return client.list_stdio_tools(command, args, cwd=cwd, environment=environment)
        raise ValueError(f"MCP server runtime is not supported yet: {kind}")

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        kind = runtime_kind(installation)
        if kind == "remote":
            url, headers = require_remote_installation(installation)
            return client.call_tool(
                url,
                headers,
                tool_name=tool_name,
                arguments=arguments,
            )
        if kind == "package":
            command, args, cwd, environment = package_runtime(installation)
            return client.call_stdio_tool(
                command,
                args,
                cwd=cwd,
                environment=environment,
                tool_name=tool_name,
                arguments=arguments,
            )
        raise ValueError(f"MCP server runtime is not supported yet: {kind}")


def get_runtime_manager() -> MCPRuntimeManager:
    return DefaultMCPRuntimeManager()
