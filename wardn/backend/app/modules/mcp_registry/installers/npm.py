import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.mcp_registry.installers.support import (
    ConfigValues,
    MCPRuntimeInstall,
    configured_package_arguments,
    materialize_config_files,
    normalized_package_version,
    npm_bin_requires_node,
    npm_package_bin,
    package_secret_config,
    public_package_config,
    require_config_values,
    run_install_command,
    write_runtime_manifest,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import MCPServerVersion


def npm_package_directory(install_path: Path, identifier: str) -> Path:
    return install_path / "node_modules" / identifier


def native_http_transport_process(package: dict[str, Any]) -> tuple[str, list[str]] | None:
    transport = package.get("transport")
    if not isinstance(transport, dict):
        return None
    transport_type = str(transport.get("type") or "").strip().lower().replace("-", "_")
    if transport_type != "streamable_http":
        return None
    command = str(transport.get("command") or "").strip()
    if not command:
        return None
    raw_args = transport.get("args")
    args = [str(arg) for arg in raw_args] if isinstance(raw_args, list) else []
    return command, args


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
    native_http_process = native_http_transport_process(package)
    public_package = public_package_config(package, env_vars, package_args, config_values)
    if executable and npm_bin_requires_node(executable):
        command = "node"
        runtime_args = [str(executable), *configured_args]
        runtime_cwd = str(install_path)
    elif executable:
        runtime_args = configured_args
        runtime_cwd = str(install_path)
    elif native_http_process is not None:
        command, transport_args = native_http_process
        runtime_args = [*(transport_args or ["start"]), *configured_args]
        runtime_cwd = str(npm_package_directory(install_path, identifier))
    else:
        runtime_args = ["--offline", identifier, *configured_args]
        runtime_cwd = str(install_path)
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
        "cwd": runtime_cwd,
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

class NpmInstaller:
    def install(
        self,
        server: MCPServerVersion,
        package: dict[str, Any],
        install_path: Path,
        config_values: ConfigValues,
    ) -> MCPRuntimeInstall:
        return build_npm_install(server, package, install_path, config_values)
