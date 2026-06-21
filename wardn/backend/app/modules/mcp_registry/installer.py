import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationUnsupportedError,
)
from app.modules.mcp_registry.models import MCPServerVersion


@dataclass(frozen=True)
class MCPRuntimeInstall:
    install_type: str
    install_path: str
    runtime_config: dict[str, Any]
    secret_config: dict[str, Any]
    status: str
    install_error: str = ""


def safe_path_component(value: str) -> str:
    component = re.sub(r"[^a-zA-Z0-9._-]+", "__", value.strip())
    return component.strip("._-") or "server"


def default_install_root() -> Path:
    return Path(get_settings().mcp_install_root).expanduser().resolve()


def server_install_path(
    server: MCPServerVersion,
    install_root: Path | None = None,
    config_name: str = "default",
) -> Path:
    root = install_root or default_install_root()
    return (
        root
        / safe_path_component(server.name)
        / safe_path_component(config_name)
        / safe_path_component(server.version)
    )


def remove_installation_artifacts(path: str) -> None:
    if not path:
        return
    shutil.rmtree(path, ignore_errors=True)


def has_required_secret(values: list[dict[str, Any]]) -> bool:
    return any(item.get("isRequired") and item.get("isSecret") for item in values)


def write_runtime_manifest(install_path: Path, runtime_config: dict[str, Any]) -> None:
    install_path.mkdir(parents=True, exist_ok=True)
    manifest_path = install_path / "runtime.json"
    manifest_path.write_text(
        json.dumps(runtime_config, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_secret_manifest(install_path: Path, secret_config: dict[str, Any]) -> None:
    if not secret_config:
        return
    secret_path = install_path / "runtime.secrets.json"
    secret_path.write_text(
        json.dumps(secret_config, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    secret_path.chmod(0o600)


def rewrite_path_prefix(value: Any, old_path: Path, new_path: Path) -> Any:
    old_prefix = os.fspath(old_path)
    new_prefix = os.fspath(new_path)
    if isinstance(value, str) and value.startswith(old_prefix):
        return f"{new_prefix}{value[len(old_prefix):]}"
    if isinstance(value, dict):
        return {key: rewrite_path_prefix(item, old_path, new_path) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_path_prefix(item, old_path, new_path) for item in value]
    return value


def required_fields(definitions: list[dict[str, Any]]) -> list[str]:
    fields = []
    for definition in definitions:
        if not definition.get("isRequired"):
            continue
        name = definition.get("name")
        if isinstance(name, str) and name:
            fields.append(name)
    return fields


def named_fields(definitions: list[dict[str, Any]]) -> list[str]:
    fields = []
    for definition in definitions:
        name = definition.get("name")
        if isinstance(name, str) and name:
            fields.append(name)
    return fields


def configured_values(
    definitions: list[dict[str, Any]],
    config_values: dict[str, str],
) -> dict[str, str]:
    return {
        name: config_values[name]
        for name in named_fields(definitions)
        if config_values.get(name)
    }


def truthy_config_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configured_package_arguments(
    definitions: list[dict[str, Any]],
    config_values: dict[str, str],
) -> list[str]:
    args = []
    for definition in definitions:
        static_value = definition.get("value")
        name = definition.get("name")
        flag = definition.get("flag")
        format_name = str(definition.get("format") or "string")

        if static_value and not name:
            args.append(str(static_value))
            continue
        if not isinstance(name, str) or not name:
            continue

        raw_value = config_values.get(name)
        if raw_value is None:
            raw_value = str(definition.get("default") or "")
        raw_value = str(raw_value)

        if format_name == "boolean":
            if truthy_config_value(raw_value):
                args.append(str(flag or static_value or name))
            continue
        if not raw_value:
            continue
        if flag:
            args.append(str(flag))
        args.append(raw_value)
    return args


def custom_header_values(config_values: dict[str, str]) -> dict[str, str]:
    header_prefix = "headers."
    headers = {}
    for key, value in config_values.items():
        if not key.startswith(header_prefix) or not value:
            continue
        header_name = key.removeprefix(header_prefix).strip()
        if header_name:
            headers[header_name] = value
    return headers


def require_config_values(
    definitions: list[dict[str, Any]],
    config_values: dict[str, str],
    *,
    label: str,
) -> None:
    missing = [name for name in required_fields(definitions) if not config_values.get(name)]
    if missing:
        raise MCPServerInstallationUnsupportedError(
            f"Missing required {label}: {', '.join(missing)}"
        )


def public_package_config(
    package: dict[str, Any],
    env_vars: list[dict[str, Any]],
    package_args: list[dict[str, Any]],
    config_values: dict[str, str],
) -> dict[str, Any]:
    public_package = dict(package)
    if env_vars:
        public_package["environmentVariables"] = [
            {
                **env_var,
                "configured": bool(config_values.get(str(env_var.get("name") or ""))),
            }
            for env_var in env_vars
        ]
    if package_args:
        public_package["packageArguments"] = [
            {
                **argument,
                "configured": bool(config_values.get(str(argument.get("name") or ""))),
            }
            if argument.get("name")
            else argument
            for argument in package_args
        ]
    custom_headers = custom_header_values(config_values)
    if custom_headers:
        public_package["headers"] = [
            {
                "name": name,
                "configured": True,
                "custom": True,
                "isSecret": True,
            }
            for name in custom_headers
        ]
    return public_package


def package_secret_config(
    env_vars: list[dict[str, Any]],
    package_args: list[dict[str, Any]],
    config_values: dict[str, str],
) -> dict[str, dict[str, str]]:
    secret_config = {}
    configured_env = configured_values(env_vars, config_values)
    configured_args = configured_values(package_args, config_values)
    custom_headers = custom_header_values(config_values)
    if configured_env:
        secret_config["environment"] = configured_env
    if configured_args:
        secret_config["packageArguments"] = configured_args
    if custom_headers:
        secret_config["headers"] = custom_headers
    return secret_config


def parse_mcp_response_body(body: str) -> dict[str, Any]:
    body = body.strip()
    if not body:
        return {}
    if "data:" in body:
        for line in body.splitlines():
            if line.startswith("data:"):
                data = line.removeprefix("data:").strip()
                if data and data != "[DONE]":
                    return json.loads(data)
        return {}
    return json.loads(body)


def send_remote_mcp_request(
    url: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "Wardn/0.1 MCP Registry Installer",
    }
    if extra_headers:
        headers.update(extra_headers)
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            return parse_mcp_response_body(body), response.headers.get("Mcp-Session-Id")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        if detail:
            try:
                payload = json.loads(detail)
                detail = payload.get("detail") or payload.get("message") or detail
            except json.JSONDecodeError:
                pass
        raise MCPServerInstallationFailedError(
            f"remote MCP server returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise MCPServerInstallationFailedError(
            f"remote MCP server is not reachable: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MCPServerInstallationFailedError(
            "remote MCP server returned an invalid MCP response"
        ) from exc


def verify_remote_mcp_server(
    remote: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = str(remote.get("url") or "")
    if not url:
        raise MCPServerInstallationFailedError("remote MCP server URL is missing")

    initialize_response, session_id = send_remote_mcp_request(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "wardn", "version": "0.1.0"},
            },
        },
        extra_headers=extra_headers,
    )
    if "error" in initialize_response:
        raise MCPServerInstallationFailedError(
            f"remote MCP initialize failed: {initialize_response['error']}"
        )
    if "result" not in initialize_response:
        raise MCPServerInstallationFailedError("remote MCP initialize returned no result")

    try:
        send_remote_mcp_request(
            url,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            session_id=session_id,
            extra_headers=extra_headers,
        )
    except MCPServerInstallationFailedError:
        # Some HTTP MCP servers return an empty/no-content response for notifications.
        # Continue to tools/list, which is the meaningful usability check.
        pass

    tools_response, _ = send_remote_mcp_request(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id=session_id,
        extra_headers=extra_headers,
    )
    if "error" in tools_response:
        raise MCPServerInstallationFailedError(
            f"remote MCP tools/list failed: {tools_response['error']}"
        )
    tools = tools_response.get("result", {}).get("tools")
    if not isinstance(tools, list):
        raise MCPServerInstallationFailedError("remote MCP tools/list returned no tools array")

    return {
        "protocolVersion": initialize_response.get("result", {}).get("protocolVersion", ""),
        "serverInfo": initialize_response.get("result", {}).get("serverInfo", {}),
        "toolCount": len(tools),
        "verifiedAt": datetime.now(UTC).isoformat(),
    }


def run_install_command(command: list[str], *, cwd: Path) -> None:
    try:
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise MCPServerInstallationUnsupportedError(
            f"required installer is not available: {command[0]}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        output = (exc.stderr or exc.stdout or "").strip()
        detail = output.splitlines()[-1] if output else str(exc)
        raise MCPServerInstallationFailedError(detail) from exc
    except subprocess.TimeoutExpired as exc:
        raise MCPServerInstallationFailedError("installer timed out") from exc


def npm_package_bin(install_path: Path, identifier: str) -> Path | None:
    package_json_path = install_path / "node_modules" / identifier / "package.json"
    if not package_json_path.exists():
        return None

    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    bin_value = package_json.get("bin")
    if isinstance(bin_value, str):
        bin_name = Path(bin_value).name
    elif isinstance(bin_value, dict) and bin_value:
        bin_name = next(iter(bin_value))
    else:
        return None

    executable = install_path / "node_modules" / ".bin" / bin_name
    return executable if executable.exists() else None


def build_remote_install(
    server: MCPServerVersion,
    install_path: Path,
    config_values: dict[str, str],
) -> MCPRuntimeInstall:
    remote = server.remotes[0]
    headers = remote.get("headers", []) if isinstance(remote.get("headers"), list) else []
    require_config_values(headers, config_values, label="connection settings")
    configured_headers = {
        **custom_header_values(config_values),
        **configured_values(headers, config_values),
    }
    verification = verify_remote_mcp_server(remote, extra_headers=configured_headers)
    public_remote = dict(remote)
    public_headers = [
        {
            **header,
            "configured": bool(config_values.get(str(header.get("name") or ""))),
        }
        for header in headers
    ]
    custom_headers = custom_header_values(config_values)
    public_headers.extend(
        {
            "name": name,
            "isSecret": True,
            "isRequired": False,
            "configured": True,
            "custom": True,
        }
        for name in custom_headers
        if name not in named_fields(headers)
    )
    if public_headers:
        public_remote["headers"] = public_headers
    secret_config = {"headers": configured_headers} if configured_headers else {}
    runtime_config = {
        "kind": "remote",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "transport": public_remote,
        "requiresConfiguration": False,
        "verification": verification,
    }
    write_runtime_manifest(install_path, runtime_config)
    write_secret_manifest(install_path, secret_config)
    return MCPRuntimeInstall(
        install_type="remote",
        install_path=str(install_path),
        runtime_config=runtime_config,
        secret_config=secret_config,
        status="enabled",
    )


def build_npm_install(
    server: MCPServerVersion,
    package: dict[str, Any],
    install_path: Path,
    config_values: dict[str, str],
) -> MCPRuntimeInstall:
    identifier = str(package["identifier"])
    version = str(package.get("version") or server.version)
    install_path.mkdir(parents=True, exist_ok=True)
    (install_path / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "name": "wardn-managed-mcp-install",
                "dependencies": {identifier: version},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    run_install_command(
        ["npm", "install", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
        cwd=install_path,
    )

    executable = npm_package_bin(install_path, identifier)
    command = str(executable) if executable else "npx"
    env_vars = (
        package.get("environmentVariables", [])
        if isinstance(package.get("environmentVariables"), list)
        else []
    )
    package_args = (
        package.get("packageArguments", [])
        if isinstance(package.get("packageArguments"), list)
        else []
    )
    require_config_values(env_vars, config_values, label="environment variables")
    require_config_values(package_args, config_values, label="package arguments")
    configured_env = configured_values(env_vars, config_values)
    configured_args = configured_package_arguments(package_args, config_values)
    public_package = public_package_config(package, env_vars, package_args, config_values)
    if executable:
        runtime_args = configured_args
    else:
        runtime_args = ["--offline", identifier, *configured_args]
    secret_config = package_secret_config(env_vars, package_args, config_values)
    runtime_config = {
        "kind": "package",
        "registryType": "npm",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "command": command,
        "args": runtime_args,
        "cwd": str(install_path),
        "requiresConfiguration": False,
    }
    write_runtime_manifest(install_path, runtime_config)
    write_secret_manifest(install_path, secret_config)
    return MCPRuntimeInstall(
        install_type="npm",
        install_path=str(install_path),
        runtime_config=runtime_config,
        secret_config=secret_config,
        status="enabled",
    )


def build_pypi_install(
    server: MCPServerVersion,
    package: dict[str, Any],
    install_path: Path,
    config_values: dict[str, str],
) -> MCPRuntimeInstall:
    identifier = str(package["identifier"])
    version = str(package.get("version") or server.version)
    venv_path = install_path / "venv"
    install_path.mkdir(parents=True, exist_ok=True)
    run_install_command([sys.executable, "-m", "venv", str(venv_path)], cwd=install_path)
    pip_path = venv_path / "bin" / "pip"
    python_path = venv_path / "bin" / "python"
    run_install_command([str(pip_path), "install", f"{identifier}=={version}"], cwd=install_path)

    env_vars = (
        package.get("environmentVariables", [])
        if isinstance(package.get("environmentVariables"), list)
        else []
    )
    package_args = (
        package.get("packageArguments", [])
        if isinstance(package.get("packageArguments"), list)
        else []
    )
    require_config_values(env_vars, config_values, label="environment variables")
    require_config_values(package_args, config_values, label="package arguments")
    configured_env = configured_values(env_vars, config_values)
    configured_args = configured_package_arguments(package_args, config_values)
    public_package = public_package_config(package, env_vars, package_args, config_values)
    secret_config = package_secret_config(env_vars, package_args, config_values)
    runtime_config = {
        "kind": "package",
        "registryType": "pypi",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "command": str(python_path),
        "args": ["-m", identifier.replace("-", "_"), *configured_args],
        "cwd": str(install_path),
        "requiresConfiguration": False,
    }
    write_runtime_manifest(install_path, runtime_config)
    write_secret_manifest(install_path, secret_config)
    return MCPRuntimeInstall(
        install_type="pypi",
        install_path=str(install_path),
        runtime_config=runtime_config,
        secret_config=secret_config,
        status="enabled",
    )


def build_uvx_install(
    server: MCPServerVersion,
    package: dict[str, Any],
    install_path: Path,
    config_values: dict[str, str],
) -> MCPRuntimeInstall:
    identifier = str(package["identifier"])
    executable = shutil.which("uvx")
    if not executable:
        raise MCPServerInstallationUnsupportedError("required installer is not available: uvx")

    install_path.mkdir(parents=True, exist_ok=True)
    env_vars = (
        package.get("environmentVariables", [])
        if isinstance(package.get("environmentVariables"), list)
        else []
    )
    package_args = (
        package.get("packageArguments", [])
        if isinstance(package.get("packageArguments"), list)
        else []
    )
    require_config_values(env_vars, config_values, label="environment variables")
    require_config_values(package_args, config_values, label="package arguments")
    configured_env = configured_values(env_vars, config_values)
    configured_args = configured_package_arguments(package_args, config_values)
    public_package = public_package_config(package, env_vars, package_args, config_values)
    secret_config = package_secret_config(env_vars, package_args, config_values)
    runtime_config = {
        "kind": "package",
        "registryType": "uvx",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "command": executable,
        "args": [identifier, *configured_args],
        "cwd": str(install_path),
        "requiresConfiguration": False,
    }
    write_runtime_manifest(install_path, runtime_config)
    write_secret_manifest(install_path, secret_config)
    return MCPRuntimeInstall(
        install_type="uvx",
        install_path=str(install_path),
        runtime_config=runtime_config,
        secret_config=secret_config,
        status="enabled",
    )


def build_oci_install(
    server: MCPServerVersion,
    package: dict[str, Any],
    install_path: Path,
    config_values: dict[str, str],
) -> MCPRuntimeInstall:
    identifier = str(package["identifier"])
    executable = shutil.which("docker")
    if not executable:
        raise MCPServerInstallationUnsupportedError("required installer is not available: docker")

    install_path.mkdir(parents=True, exist_ok=True)
    run_install_command([executable, "pull", identifier], cwd=install_path)

    env_vars = (
        package.get("environmentVariables", [])
        if isinstance(package.get("environmentVariables"), list)
        else []
    )
    package_args = (
        package.get("packageArguments", [])
        if isinstance(package.get("packageArguments"), list)
        else []
    )
    require_config_values(env_vars, config_values, label="environment variables")
    require_config_values(package_args, config_values, label="package arguments")
    configured_env = configured_values(env_vars, config_values)
    configured_args = configured_package_arguments(package_args, config_values)
    public_package = public_package_config(package, env_vars, package_args, config_values)
    secret_config = package_secret_config(env_vars, package_args, config_values)
    docker_env_names = [
        *configured_env.keys(),
        *(["WARDN_MCP_CUSTOM_HEADERS"] if secret_config.get("headers") else []),
    ]
    docker_env_args = [
        argument
        for name in docker_env_names
        for argument in ("-e", name)
    ]
    runtime_config = {
        "kind": "package",
        "registryType": "oci",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "command": executable,
        "args": ["run", "--rm", "-i", *docker_env_args, identifier, *configured_args],
        "cwd": str(install_path),
        "requiresConfiguration": False,
    }
    write_runtime_manifest(install_path, runtime_config)
    write_secret_manifest(install_path, secret_config)
    return MCPRuntimeInstall(
        install_type="oci",
        install_path=str(install_path),
        runtime_config=runtime_config,
        secret_config=secret_config,
        status="enabled",
    )


def selected_install_target(server: MCPServerVersion, config_values: dict[str, str]) -> str:
    remote_headers = [
        item
        for remote in server.remotes or []
        for item in remote.get("headers", [])
        if isinstance(item, dict)
    ]
    package_environment = [
        item
        for package in server.packages or []
        for item in package.get("environmentVariables", [])
        if isinstance(item, dict)
    ]
    package_arguments = [
        item
        for package in server.packages or []
        for item in package.get("packageArguments", [])
        if isinstance(item, dict)
    ]
    config_keys = {key for key, value in config_values.items() if value}
    package_field_names = set(named_fields([*package_environment, *package_arguments]))
    remote_field_names = set(named_fields(remote_headers))

    if server.packages and config_keys.intersection(package_field_names):
        return "package"
    if server.remotes and (
        config_keys.intersection(remote_field_names)
        or any(key.startswith("headers.") for key in config_keys)
    ):
        return "remote"
    if server.packages and not server.remotes:
        return "package"
    if server.remotes and not server.packages:
        return "remote"
    if server.packages:
        return "package"
    return "remote"


def build_package_install(
    server: MCPServerVersion,
    install_path: Path,
    config_values: dict[str, str],
) -> MCPRuntimeInstall:
    package = server.packages[0]
    registry_type = str(package.get("registryType", "")).casefold()
    if registry_type == "npm":
        return build_npm_install(server, package, install_path, config_values)
    if registry_type == "pypi":
        return build_pypi_install(server, package, install_path, config_values)
    if registry_type == "uvx":
        return build_uvx_install(server, package, install_path, config_values)
    if registry_type == "oci":
        return build_oci_install(server, package, install_path, config_values)
    raise MCPServerInstallationUnsupportedError(
        f"MCP server package registry is not supported yet: {registry_type or 'unknown'}"
    )


def install_server_runtime(
    server: MCPServerVersion,
    *,
    config_values: dict[str, str] | None = None,
    install_target: str | None = None,
    install_root: Path | None = None,
    config_name: str = "default",
) -> MCPRuntimeInstall:
    config_values = config_values or {}
    install_path = server_install_path(server, install_root, config_name)
    temporary_path = install_path.with_name(f"{install_path.name}.tmp")
    shutil.rmtree(temporary_path, ignore_errors=True)
    temporary_path.mkdir(parents=True, exist_ok=True)

    try:
        selected_target = install_target or selected_install_target(server, config_values)
        if selected_target == "remote" and server.remotes:
            runtime_install = build_remote_install(server, temporary_path, config_values)
        elif selected_target == "package" and server.packages:
            runtime_install = build_package_install(server, temporary_path, config_values)
        else:
            raise MCPServerInstallationUnsupportedError(
                "MCP server does not define a remote or package installation target"
            )

        shutil.rmtree(install_path, ignore_errors=True)
        temporary_path.rename(install_path)
        runtime_config = rewrite_path_prefix(
            runtime_install.runtime_config,
            temporary_path,
            install_path,
        )
        runtime_config["installPath"] = str(install_path)
        write_runtime_manifest(install_path, runtime_config)
        write_secret_manifest(install_path, runtime_install.secret_config)
        return MCPRuntimeInstall(
            install_type=runtime_install.install_type,
            install_path=str(install_path),
            runtime_config=runtime_config,
            secret_config=runtime_install.secret_config,
            status=runtime_install.status,
            install_error=runtime_install.install_error,
        )
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise
