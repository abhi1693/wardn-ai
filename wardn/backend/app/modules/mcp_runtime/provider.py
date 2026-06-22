import hashlib
import hmac
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation

if TYPE_CHECKING:
    from app.modules.mcp_runtime.models import MCPRuntimeSession

RUNTIME_KIND_REMOTE = "remote"
RUNTIME_KIND_PACKAGE = "package"

RUNTIME_PROVIDER_AUTO = "auto"
RUNTIME_PROVIDER_REMOTE = "remote"
RUNTIME_PROVIDER_LOCAL = "local"
RUNTIME_PROVIDER_KUBERNETES = "kubernetes"

RUNTIME_TRANSPORT_STDIO = "stdio"
WARDN_CUSTOM_HEADERS_ENV = "WARDN_MCP_CUSTOM_HEADERS"


class MCPRuntimeProvider(Protocol):
    name: str

    def supports(self, installation: MCPServerInstallation) -> bool:
        ...

    def runtime_spec(self, installation: MCPServerInstallation) -> "RuntimeSpec":
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

    def stop_runtime(self, runtime_session: "MCPRuntimeSession") -> None:
        ...


@dataclass(frozen=True)
class RuntimeSpec:
    installation_id: str
    server_name: str
    server_version: str
    provider_name: str
    runtime_kind: str
    transport: str
    runtime_config_fingerprint: str
    secret_config_fingerprint: str
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    endpoint_url: str = ""
    workspace_id: str = ""

    def fingerprint(self) -> str:
        return fingerprint_payload(
            {
                "installationId": self.installation_id,
                "serverName": self.server_name,
                "serverVersion": self.server_version,
                "providerName": self.provider_name,
                "runtimeKind": self.runtime_kind,
                "transport": self.transport,
                "runtimeConfigFingerprint": self.runtime_config_fingerprint,
                "secretConfigFingerprint": self.secret_config_fingerprint,
                "command": self.command,
                "args": list(self.args),
                "cwd": self.cwd,
                "endpointUrl": self.endpoint_url,
                "workspaceId": self.workspace_id,
            }
        )


@dataclass(frozen=True)
class PackageRuntimeSpec:
    command: str
    args: list[str]
    cwd: str
    environment: dict[str, str]

    def __iter__(self):
        yield self.command
        yield self.args
        yield self.cwd
        yield self.environment


@dataclass(frozen=True)
class RemoteRuntimeSpec:
    url: str
    headers: dict[str, str]

    def __iter__(self):
        yield self.url
        yield self.headers


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)


def fingerprint_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def secret_fingerprint_payload(payload: Any) -> str:
    key = get_settings().session_secret.encode("utf-8")
    return hmac.new(key, canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


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
        values[WARDN_CUSTOM_HEADERS_ENV] = json.dumps(
            headers,
            separators=(",", ":"),
            sort_keys=True,
        )
    return values


def require_remote_installation(installation: MCPServerInstallation) -> RemoteRuntimeSpec:
    if runtime_kind(installation) != RUNTIME_KIND_REMOTE:
        raise ValueError("installation is not a remote MCP server")
    url = remote_url(installation)
    if not url:
        raise ValueError("remote MCP server URL is missing from installation runtime")
    return RemoteRuntimeSpec(url=url, headers=secret_headers(installation))


def base_runtime_spec(
    installation: MCPServerInstallation,
    *,
    provider_name: str,
    transport: str,
    command: str = "",
    args: list[str] | tuple[str, ...] = (),
    cwd: str = "",
    endpoint_url: str = "",
) -> RuntimeSpec:
    return RuntimeSpec(
        installation_id=str(getattr(installation, "id", "")),
        server_name=installation.server_name,
        server_version=installation.installed_version,
        provider_name=provider_name,
        runtime_kind=runtime_kind(installation),
        transport=transport,
        runtime_config_fingerprint=fingerprint_payload(installation.runtime_config or {}),
        secret_config_fingerprint=secret_fingerprint_payload(installation.secret_config or {}),
        command=command,
        args=tuple(args),
        cwd=cwd,
        endpoint_url=endpoint_url,
        workspace_id=str(installation.workspace_id or ""),
    )


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


def package_runtime(installation: MCPServerInstallation) -> PackageRuntimeSpec:
    if runtime_kind(installation) != RUNTIME_KIND_PACKAGE:
        raise ValueError("installation is not a package MCP server")

    runtime_config = installation.runtime_config or {}
    transport = runtime_config.get("transport")
    if isinstance(transport, dict) and transport.get("type") not in (None, RUNTIME_TRANSPORT_STDIO):
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
    return PackageRuntimeSpec(
        command=command,
        args=args,
        cwd=cwd,
        environment=secret_environment(installation),
    )
