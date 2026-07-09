import base64
import binascii
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

RUNTIME_FILE_DIR_NAME = "runtime-files"
KUBERNETES_RUNTIME_FILE_MOUNT_PATH = "/opt/wardn/runtime-files"
ConfigValues = dict[str, Any]
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {PROTOCOL_VERSION, "2025-03-26", "2024-11-05", "2024-10-07"}
)


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
    workspace_id: str | None = None,
) -> Path:
    root = install_root or default_install_root()
    path = root
    if workspace_id:
        path = path / safe_path_component(workspace_id)
    return (
        path
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


def config_value_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(by_alias=True)
        return dumped if isinstance(dumped, dict) else {}
    return {}


def config_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    mapping = config_value_mapping(value)
    if not mapping:
        return bool(value)
    if mapping.get("type") == "secret_handle":
        return bool(mapping.get("secretHandleId") or mapping.get("secret_handle_id"))
    return any(
        bool(mapping.get(key))
        for key in ("content", "contentBase64", "content_base64", "path")
    )


def config_value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    mapping = config_value_mapping(value)
    if not mapping:
        return str(value)
    if mapping.get("type") == "secret_handle":
        return ""
    for key in ("content", "contentBase64", "content_base64", "path"):
        configured = mapping.get(key)
        if configured:
            return str(configured)
    return ""


def configured_values(
    definitions: list[dict[str, Any]],
    config_values: ConfigValues,
    *,
    file_paths: dict[str, str] | None = None,
) -> dict[str, str]:
    file_paths = file_paths or {}
    return {
        name: file_paths.get(name) or config_value_text(config_values[name])
        for name in named_fields(definitions)
        if config_value_present(config_values.get(name))
    }


def truthy_config_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configured_package_arguments(
    definitions: list[dict[str, Any]],
    config_values: ConfigValues,
    *,
    file_paths: dict[str, str] | None = None,
) -> list[str]:
    args = []
    file_paths = file_paths or {}
    for definition in definitions:
        if definition.get("includeInLaunch") is False:
            continue
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
        raw_value = config_value_text(raw_value)

        if format_name == "boolean":
            if truthy_config_value(raw_value):
                args.append(str(flag or static_value or name))
            continue
        if not raw_value:
            continue
        if flag:
            args.append(str(flag))
        args.append(file_paths.get(name) or raw_value)
    return args


def oci_container_argument_definitions(
    definitions: list[dict[str, Any]],
    *,
    image: str,
) -> list[dict[str, Any]]:
    docker_wrapper_flags = {
        "run",
        "-i",
        "--interactive",
        "--rm",
        "--init",
        "--pull",
    }
    docker_wrapper_value_flags = {
        "-e",
        "--env",
        "--env-file",
        "-p",
        "--publish",
        "-v",
        "--volume",
        "--name",
        "--network",
        "--user",
        "-u",
        "--workdir",
        "-w",
        "--entrypoint",
        "--add-host",
    }
    filtered = []
    for definition in definitions:
        if definition.get("includeInLaunch") is False:
            continue
        name = str(definition.get("name") or "").strip()
        flag = str(definition.get("flag") or "").strip()
        value = str(definition.get("value") or "").strip()
        if not name and flag in docker_wrapper_flags | docker_wrapper_value_flags:
            continue
        if name.casefold() == "docker image" and value == image:
            continue
        filtered.append(definition)
    return filtered


def custom_header_values(config_values: ConfigValues) -> dict[str, str]:
    header_prefix = "headers."
    headers = {}
    for key, value in config_values.items():
        if not key.startswith(header_prefix) or not config_value_present(value):
            continue
        header_name = key.removeprefix(header_prefix).strip()
        if header_name:
            headers[header_name] = config_value_text(value)
    return headers


def normalized_package_version(value: Any) -> str:
    version = str(value or "").strip()
    if not version or version == "0.0.0":
        return "latest"
    return version


def require_config_values(
    definitions: list[dict[str, Any]],
    config_values: ConfigValues,
    *,
    label: str,
) -> None:
    missing = [
        name
        for name in required_fields(definitions)
        if not config_value_present(config_values.get(name))
    ]
    if missing:
        raise MCPServerInstallationUnsupportedError(
            f"Missing required {label}: {', '.join(missing)}"
        )


def file_config_definition(definition: dict[str, Any]) -> bool:
    format_name = str(definition.get("format") or "").strip().lower()
    if format_name in {"file", "path", "filepath", "file_path"}:
        return True
    flag = str(definition.get("flag") or "").strip().lower()
    name = str(definition.get("name") or "").strip().lower()
    return flag.endswith("-file") or flag.endswith("_file") or name.endswith("_file")


def config_file_name(name: str) -> str:
    return safe_path_component(name).replace(".", "_")


def config_file_content(raw_value: Any) -> str:
    mapping = config_value_mapping(raw_value)
    if mapping:
        content_base64 = mapping.get("contentBase64") or mapping.get("content_base64")
        if content_base64:
            try:
                return base64.b64decode(str(content_base64), validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise MCPServerInstallationUnsupportedError(
                    "file config contentBase64 must be valid UTF-8 base64 content"
                ) from exc
        if mapping.get("content"):
            return str(mapping["content"])
        raw_path = mapping.get("path")
        if raw_path:
            candidate = Path(str(raw_path)).expanduser()
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
            raise MCPServerInstallationUnsupportedError(
                f"file config path does not exist or is not readable: {raw_path}"
            )
        return ""

    candidate = Path(str(raw_value)).expanduser()
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return str(raw_value)


def config_file_payload(raw_value: Any) -> tuple[str, str]:
    mapping = config_value_mapping(raw_value)
    filename = str(mapping.get("filename") or "").strip() if mapping else ""
    return config_file_content(raw_value), filename


def materialize_config_files(
    definitions: list[dict[str, Any]],
    config_values: ConfigValues,
    install_path: Path,
) -> tuple[dict[str, str], dict[str, dict[str, str]], list[dict[str, str]]]:
    local_paths: dict[str, str] = {}
    secret_files: dict[str, dict[str, str]] = {}
    runtime_mounts: list[dict[str, str]] = []
    file_dir = install_path / RUNTIME_FILE_DIR_NAME
    for definition in definitions:
        name = definition.get("name")
        if not isinstance(name, str) or not name or not file_config_definition(definition):
            continue
        raw_value = config_values.get(name)
        if not config_value_present(raw_value):
            continue
        file_dir.mkdir(parents=True, exist_ok=True)
        key = config_file_name(name)
        local_path = file_dir / key
        content, filename = config_file_payload(raw_value)
        local_path.write_text(content, encoding="utf-8")
        local_path.chmod(0o600)
        mount_path = f"{KUBERNETES_RUNTIME_FILE_MOUNT_PATH}/{key}"
        local_paths[name] = str(local_path)
        secret_files[name] = {
            "key": key,
            "filename": filename,
            "content": content,
            "path": str(local_path),
            "mountPath": mount_path,
        }
        runtime_mounts.append(
            {
                "name": name,
                "key": key,
                "path": str(local_path),
                "mountPath": mount_path,
            }
        )
    return local_paths, secret_files, runtime_mounts


def public_package_config(
    package: dict[str, Any],
    env_vars: list[dict[str, Any]],
    package_args: list[dict[str, Any]],
    config_values: ConfigValues,
) -> dict[str, Any]:
    public_package = dict(package)
    if env_vars:
        public_package["environmentVariables"] = [
            {
                **env_var,
                "configured": config_value_present(
                    config_values.get(str(env_var.get("name") or ""))
                ),
            }
            for env_var in env_vars
        ]
    if package_args:
        public_package["packageArguments"] = [
            {
                **argument,
                "configured": config_value_present(
                    config_values.get(str(argument.get("name") or ""))
                ),
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
    config_values: ConfigValues,
    *,
    file_paths: dict[str, str] | None = None,
    secret_files: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    secret_config = {}
    configured_env = configured_values(env_vars, config_values, file_paths=file_paths)
    configured_args = configured_values(package_args, config_values, file_paths=file_paths)
    custom_headers = custom_header_values(config_values)
    if configured_env:
        secret_config["environment"] = configured_env
    if configured_args:
        secret_config["packageArguments"] = configured_args
    if custom_headers:
        secret_config["headers"] = custom_headers
    if secret_files:
        secret_config["files"] = secret_files
    return secret_config


def parse_mcp_response_body(body: str) -> dict[str, Any]:
    body = body.strip()
    if not body:
        return {}
    if "data:" in body:
        fallback: dict[str, Any] = {}
        for line in body.splitlines():
            if line.startswith("data:"):
                data = line.removeprefix("data:").strip()
                if data and data != "[DONE]":
                    payload = json.loads(data)
                    if isinstance(payload, dict):
                        if "result" in payload or "error" in payload:
                            return payload
                        fallback = payload
        return fallback
    return json.loads(body)


def send_remote_mcp_request(
    url: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
    protocol_version: str | None = None,
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
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version

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


def negotiated_protocol_version(response: dict[str, Any]) -> str:
    result = response.get("result")
    protocol_version = result.get("protocolVersion") if isinstance(result, dict) else None
    if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise MCPServerInstallationFailedError(
            f"remote MCP server negotiated unsupported protocol version: {protocol_version}"
        )
    return str(protocol_version)


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
                "protocolVersion": PROTOCOL_VERSION,
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
    protocol_version = negotiated_protocol_version(initialize_response)

    try:
        send_remote_mcp_request(
            url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id=session_id,
            extra_headers=extra_headers,
            protocol_version=protocol_version,
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
        protocol_version=protocol_version,
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


def npm_bin_requires_node(executable: Path) -> bool:
    target = executable.resolve()
    try:
        with target.open("rb") as file:
            first_line = file.readline(256)
    except OSError:
        return False
    if first_line.startswith(b"#!"):
        return False
    return target.suffix == ".js"


def parse_install_target(install_target: str | None) -> tuple[str | None, int]:
    if not install_target:
        return None, 0

    target_kind, separator, target_index = install_target.partition(":")
    if target_kind not in {"remote", "package"}:
        raise MCPServerInstallationUnsupportedError(
            f"MCP server installation target is not supported: {install_target}"
        )
    if not separator:
        return target_kind, 0
    try:
        index = int(target_index)
    except ValueError as exc:
        raise MCPServerInstallationUnsupportedError(
            f"MCP server installation target is not supported: {install_target}"
        ) from exc
    if index < 0:
        raise MCPServerInstallationUnsupportedError(
            f"MCP server installation target is not supported: {install_target}"
        )
    return target_kind, index


def indexed_install_definition(
    definitions: list[dict[str, Any]],
    index: int,
    *,
    label: str,
) -> dict[str, Any]:
    try:
        return definitions[index]
    except IndexError as exc:
        raise MCPServerInstallationUnsupportedError(
            f"MCP server does not define {label} installation target {index}"
        ) from exc


def build_remote_install(
    server: MCPServerVersion,
    install_path: Path,
    config_values: ConfigValues,
    target_index: int = 0,
) -> MCPRuntimeInstall:
    remote = indexed_install_definition(server.remotes, target_index, label="remote")
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
            "configured": config_value_present(config_values.get(str(header.get("name") or ""))),
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
    config_values: ConfigValues,
) -> MCPRuntimeInstall:
    identifier = str(package["identifier"])
    version = normalized_package_version(package.get("version") or server.version)
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
    file_paths, secret_files, runtime_mounts = materialize_config_files(
        [*env_vars, *package_args],
        config_values,
        install_path,
    )
    configured_args = configured_package_arguments(
        package_args,
        config_values,
        file_paths=file_paths,
    )
    public_package = public_package_config(package, env_vars, package_args, config_values)
    if executable and npm_bin_requires_node(executable):
        command = "node"
        runtime_args = [str(executable), *configured_args]
    elif executable:
        runtime_args = configured_args
    else:
        runtime_args = ["--offline", identifier, *configured_args]
    secret_config = package_secret_config(
        env_vars,
        package_args,
        config_values,
        file_paths=file_paths,
        secret_files=secret_files,
    )
    runtime_config = {
        "kind": "package",
        "registryType": "npm",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "fileMounts": runtime_mounts,
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
    config_values: ConfigValues,
) -> MCPRuntimeInstall:
    identifier = str(package["identifier"])
    version = normalized_package_version(package.get("version") or server.version)
    venv_path = install_path / "venv"
    install_path.mkdir(parents=True, exist_ok=True)
    run_install_command([sys.executable, "-m", "venv", str(venv_path)], cwd=install_path)
    pip_path = venv_path / "bin" / "pip"
    python_path = venv_path / "bin" / "python"
    package_spec = identifier if version == "latest" else f"{identifier}=={version}"
    run_install_command([str(pip_path), "install", package_spec], cwd=install_path)

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
    file_paths, secret_files, runtime_mounts = materialize_config_files(
        [*env_vars, *package_args],
        config_values,
        install_path,
    )
    configured_args = configured_package_arguments(
        package_args,
        config_values,
        file_paths=file_paths,
    )
    public_package = public_package_config(package, env_vars, package_args, config_values)
    secret_config = package_secret_config(
        env_vars,
        package_args,
        config_values,
        file_paths=file_paths,
        secret_files=secret_files,
    )
    runtime_config = {
        "kind": "package",
        "registryType": "pypi",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "fileMounts": runtime_mounts,
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
    config_values: ConfigValues,
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
    file_paths, secret_files, runtime_mounts = materialize_config_files(
        [*env_vars, *package_args],
        config_values,
        install_path,
    )
    configured_args = configured_package_arguments(
        package_args,
        config_values,
        file_paths=file_paths,
    )
    if identifier.startswith(("git+", "http://", "https://", "file:")) or identifier.startswith(
        (".", "/")
    ):
        if not configured_args:
            raise MCPServerInstallationUnsupportedError(
                "uvx source installs require a package argument with the command to run"
            )
        runtime_args = ["--from", identifier, *configured_args]
    else:
        runtime_args = [identifier, *configured_args]
    public_package = public_package_config(package, env_vars, package_args, config_values)
    secret_config = package_secret_config(
        env_vars,
        package_args,
        config_values,
        file_paths=file_paths,
        secret_files=secret_files,
    )
    runtime_config = {
        "kind": "package",
        "registryType": "uvx",
        "serverName": server.name,
        "version": server.version,
        "installedAt": datetime.now(UTC).isoformat(),
        "package": public_package,
        "transport": package.get("transport", {"type": "stdio"}),
        "fileMounts": runtime_mounts,
        "command": executable,
        "args": runtime_args,
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
    config_values: ConfigValues,
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
    file_paths, secret_files, runtime_mounts = materialize_config_files(
        [*env_vars, *package_args],
        config_values,
        install_path,
    )
    configured_env = configured_values(env_vars, config_values, file_paths=file_paths)
    container_package_args = oci_container_argument_definitions(
        package_args,
        image=identifier,
    )
    configured_args = configured_package_arguments(
        container_package_args,
        config_values,
        file_paths=file_paths,
    )
    public_package = public_package_config(package, env_vars, package_args, config_values)
    secret_config = package_secret_config(
        env_vars,
        package_args,
        config_values,
        file_paths=file_paths,
        secret_files=secret_files,
    )
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
        "fileMounts": runtime_mounts,
        "containerImage": identifier,
        "containerArgs": configured_args,
        "containerEnvNames": docker_env_names,
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


def selected_install_target(server: MCPServerVersion, config_values: ConfigValues) -> str:
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
    config_keys = {key for key, value in config_values.items() if config_value_present(value)}
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
    config_values: ConfigValues,
    target_index: int = 0,
) -> MCPRuntimeInstall:
    package = indexed_install_definition(server.packages, target_index, label="package")
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
    config_values: ConfigValues | None = None,
    install_target: str | None = None,
    install_root: Path | None = None,
    config_name: str = "default",
    workspace_id: str | None = None,
) -> MCPRuntimeInstall:
    config_values = config_values or {}
    install_path = server_install_path(server, install_root, config_name, workspace_id)
    temporary_path = install_path.with_name(f"{install_path.name}.tmp")
    shutil.rmtree(temporary_path, ignore_errors=True)
    temporary_path.mkdir(parents=True, exist_ok=True)

    try:
        parsed_target, target_index = parse_install_target(install_target)
        selected_target = parsed_target or selected_install_target(server, config_values)
        if selected_target == "remote" and server.remotes:
            runtime_install = build_remote_install(
                server,
                temporary_path,
                config_values,
                target_index,
            )
        elif selected_target == "package" and server.packages:
            runtime_install = build_package_install(
                server,
                temporary_path,
                config_values,
                target_index,
            )
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
        secret_config = rewrite_path_prefix(
            runtime_install.secret_config,
            temporary_path,
            install_path,
        )
        runtime_config["installPath"] = str(install_path)
        write_runtime_manifest(install_path, runtime_config)
        write_secret_manifest(install_path, secret_config)
        return MCPRuntimeInstall(
            install_type=runtime_install.install_type,
            install_path=str(install_path),
            runtime_config=runtime_config,
            secret_config=secret_config,
            status=runtime_install.status,
            install_error=runtime_install.install_error,
        )
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise
