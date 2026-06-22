import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
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


@dataclass
class ManagedStdioSession:
    session: client.MCPStdioSession
    next_request_id: int = 2


class DefaultMCPRuntimeManager:
    def __init__(self) -> None:
        self._stdio_sessions: dict[str, ManagedStdioSession] = {}
        self._stdio_lock = Lock()

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
            return self._with_stdio_session(
                installation,
                command=command,
                args=args,
                cwd=cwd,
                environment=environment,
                action=lambda managed: self._list_stdio_tools(managed),
            )
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
            return self._with_stdio_session(
                installation,
                command=command,
                args=args,
                cwd=cwd,
                environment=environment,
                action=lambda managed: self._call_stdio_tool(
                    managed,
                    tool_name=tool_name,
                    arguments=arguments,
                ),
            )
        raise ValueError(f"MCP server runtime is not supported yet: {kind}")

    def _stdio_session_key(
        self,
        installation: MCPServerInstallation,
        *,
        command: str,
        args: list[str],
        cwd: str,
        environment: dict[str, str],
    ) -> str:
        return json.dumps(
            {
                "installationId": str(getattr(installation, "id", "")),
                "command": command,
                "args": args,
                "cwd": cwd,
                "environment": environment,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def _with_stdio_session(
        self,
        installation: MCPServerInstallation,
        *,
        command: str,
        args: list[str],
        cwd: str,
        environment: dict[str, str],
        action,
    ):
        key = self._stdio_session_key(
            installation,
            command=command,
            args=args,
            cwd=cwd,
            environment=environment,
        )
        with self._stdio_lock:
            managed = self._stdio_sessions.get(key)
            if managed is None or managed.session.process.poll() is not None:
                managed = ManagedStdioSession(
                    client.open_stdio_session(command, args, cwd=cwd, environment=environment)
                )
                self._stdio_sessions[key] = managed
            try:
                return action(managed)
            except Exception:
                self._drop_stdio_session(key)
                raise

    def _drop_stdio_session(self, key: str) -> None:
        managed = self._stdio_sessions.pop(key, None)
        if managed is not None:
            client.close_stdio_session(managed.session)

    def _list_stdio_tools(self, managed: ManagedStdioSession) -> list[dict[str, Any]]:
        tools, next_request_id = client.list_stdio_session_tools(
            managed.session,
            request_id_start=managed.next_request_id,
        )
        managed.next_request_id = next_request_id
        return tools

    def _call_stdio_tool(
        self,
        managed: ManagedStdioSession,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = managed.next_request_id
        managed.next_request_id += 1
        return client.call_stdio_session_tool(
            managed.session,
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
        )


def get_runtime_manager() -> MCPRuntimeManager:
    return _DEFAULT_RUNTIME_MANAGER


_DEFAULT_RUNTIME_MANAGER = DefaultMCPRuntimeManager()
