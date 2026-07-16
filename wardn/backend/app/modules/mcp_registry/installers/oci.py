import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.mcp_registry.exceptions import MCPServerInstallationUnsupportedError
from app.modules.mcp_registry.installers.support import (
    ConfigValues,
    MCPRuntimeInstall,
    configured_package_arguments,
    configured_values,
    materialize_config_files,
    oci_container_argument_definitions,
    package_secret_config,
    public_package_config,
    require_config_values,
    run_install_command,
    write_runtime_manifest,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import MCPServerVersion


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

class OCIInstaller:
    def install(
        self,
        server: MCPServerVersion,
        package: dict[str, Any],
        install_path: Path,
        config_values: ConfigValues,
    ) -> MCPRuntimeInstall:
        return build_oci_install(server, package, install_path, config_values)

