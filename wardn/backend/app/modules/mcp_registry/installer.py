import shutil
from pathlib import Path
from typing import Any, Protocol

from app.modules.mcp_registry.exceptions import MCPServerInstallationUnsupportedError
from app.modules.mcp_registry.installers.npm import NpmInstaller, build_npm_install
from app.modules.mcp_registry.installers.oci import OCIInstaller, build_oci_install
from app.modules.mcp_registry.installers.python import (
    PythonInstaller,
    build_pypi_install,
    build_uvx_install,
)
from app.modules.mcp_registry.installers.remote import (
    RemoteInstaller,
    negotiated_protocol_version,
    parse_mcp_response_body,
    send_remote_mcp_request,
    verify_remote_mcp_server,
)
from app.modules.mcp_registry.installers.support import (
    ConfigValues,
    MCPRuntimeInstall,
    config_file_content,
    config_file_name,
    config_file_payload,
    config_value_mapping,
    config_value_present,
    config_value_text,
    configured_package_arguments,
    configured_values,
    custom_header_values,
    default_install_root,
    file_config_definition,
    indexed_install_definition,
    materialize_config_files,
    named_fields,
    npm_bin_requires_node,
    npm_package_bin,
    oci_container_argument_definitions,
    package_secret_config,
    parse_install_target,
    public_package_config,
    remove_installation_artifacts,
    require_config_values,
    required_fields,
    rewrite_path_prefix,
    run_install_command,
    safe_path_component,
    server_install_path,
    write_runtime_manifest,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import MCPServerVersion


class PackageInstaller(Protocol):
    def install(
        self,
        server: MCPServerVersion,
        package: dict[str, Any],
        install_path: Path,
        config_values: ConfigValues,
    ) -> MCPRuntimeInstall: ...


_python_installer = PythonInstaller()
PACKAGE_INSTALLERS: dict[str, PackageInstaller] = {
    "npm": NpmInstaller(),
    "pypi": _python_installer,
    "uvx": _python_installer,
    "oci": OCIInstaller(),
}
REMOTE_INSTALLER = RemoteInstaller()


def build_remote_install(
    server: MCPServerVersion,
    install_path: Path,
    config_values: ConfigValues,
    target_index: int = 0,
) -> MCPRuntimeInstall:
    return REMOTE_INSTALLER.install(server, install_path, config_values, target_index)


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
    strategy = PACKAGE_INSTALLERS.get(registry_type)
    if strategy is None:
        raise MCPServerInstallationUnsupportedError(
            f"MCP server package registry is not supported yet: {registry_type or 'unknown'}"
        )
    return strategy.install(server, package, install_path, config_values)


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
    backup_path = install_path.with_name(f"{install_path.name}.backup")
    if backup_path.exists() and not install_path.exists():
        backup_path.rename(install_path)
    shutil.rmtree(temporary_path, ignore_errors=True)
    shutil.rmtree(backup_path, ignore_errors=True)
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

        if install_path.exists():
            install_path.rename(backup_path)
        try:
            temporary_path.rename(install_path)
        except Exception:
            if backup_path.exists() and not install_path.exists():
                backup_path.rename(install_path)
            raise
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
        shutil.rmtree(backup_path, ignore_errors=True)
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
        if backup_path.exists():
            shutil.rmtree(install_path, ignore_errors=True)
            backup_path.rename(install_path)
        raise


__all__ = [
    "ConfigValues",
    "MCPRuntimeInstall",
    "NpmInstaller",
    "OCIInstaller",
    "PACKAGE_INSTALLERS",
    "PythonInstaller",
    "REMOTE_INSTALLER",
    "RemoteInstaller",
    "build_npm_install",
    "build_oci_install",
    "build_package_install",
    "build_pypi_install",
    "build_remote_install",
    "build_uvx_install",
    "config_file_content",
    "config_file_name",
    "config_file_payload",
    "config_value_mapping",
    "config_value_present",
    "config_value_text",
    "configured_package_arguments",
    "configured_values",
    "custom_header_values",
    "default_install_root",
    "file_config_definition",
    "indexed_install_definition",
    "install_server_runtime",
    "materialize_config_files",
    "named_fields",
    "negotiated_protocol_version",
    "npm_bin_requires_node",
    "npm_package_bin",
    "oci_container_argument_definitions",
    "package_secret_config",
    "parse_install_target",
    "parse_mcp_response_body",
    "public_package_config",
    "remove_installation_artifacts",
    "require_config_values",
    "required_fields",
    "rewrite_path_prefix",
    "run_install_command",
    "safe_path_component",
    "selected_install_target",
    "send_remote_mcp_request",
    "server_install_path",
    "verify_remote_mcp_server",
    "write_runtime_manifest",
    "write_secret_manifest",
]
