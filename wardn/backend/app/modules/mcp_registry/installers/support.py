import base64
import binascii
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationUnsupportedError,
)
from app.modules.mcp_registry.models import MCPServerVersion

RUNTIME_FILE_DIR_NAME = "runtime-files"
KUBERNETES_RUNTIME_FILE_MOUNT_PATH = "/opt/wardn/runtime-files"
ConfigValues = dict[str, Any]

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

def run_install_command(command: list[str], *, cwd: Path) -> None:
    cache_root = cwd / ".installer-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(cache_root),
        "TMPDIR": str(cache_root),
        "XDG_CACHE_HOME": str(cache_root),
        "NPM_CONFIG_CACHE": str(cache_root / "npm"),
        "PIP_CACHE_DIR": str(cache_root / "pip"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "UV_CACHE_DIR": str(cache_root / "uv"),
        "CI": "true",
        "NO_COLOR": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    try:
        subprocess.run(
            command,
            cwd=cwd,
            env=environment,
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
