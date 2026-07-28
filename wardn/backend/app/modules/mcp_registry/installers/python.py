import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.mcp_registry.exceptions import MCPServerInstallationUnsupportedError
from app.modules.mcp_registry.installers.support import (
    ConfigValues,
    MCPRuntimeInstall,
    configured_package_arguments,
    materialize_config_files,
    normalized_package_version,
    package_secret_config,
    public_package_config,
    require_config_values,
    run_install_command,
    write_runtime_manifest,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import MCPServerVersion


def package_stdio_transport(package: dict[str, Any]) -> tuple[str, list[str]]:
    transport = package.get("transport")
    if not isinstance(transport, dict):
        return "", []
    if str(transport.get("type") or "stdio").strip().lower() not in {"", "stdio"}:
        return "", []
    raw_args = transport.get("args")
    args = [str(arg) for arg in raw_args] if isinstance(raw_args, list) else []
    return str(transport.get("command") or "").strip(), args


def pypi_runtime_process(
    *,
    package: dict[str, Any],
    identifier: str,
    python_path: Path,
    venv_path: Path,
    configured_args: list[str],
) -> tuple[str, list[str]]:
    transport_command, transport_args = package_stdio_transport(package)
    transport_command_name = Path(transport_command).name
    if transport_command_name in {"python", "python3"}:
        return str(python_path), [*transport_args, *configured_args]
    if transport_command_name == "uvx" and transport_args:
        executable = Path(str(transport_args[0])).name
        return str(venv_path / "bin" / executable), [*transport_args[1:], *configured_args]
    if transport_command_name:
        return str(venv_path / "bin" / transport_command_name), [
            *transport_args,
            *configured_args,
        ]
    return str(python_path), ["-m", identifier.replace("-", "_"), *configured_args]


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
    runtime_command, runtime_args = pypi_runtime_process(
        package=package,
        identifier=identifier,
        python_path=python_path,
        venv_path=venv_path,
        configured_args=configured_args,
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
        "command": runtime_command,
        "args": runtime_args,
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

class PythonInstaller:
    def install(
        self,
        server: MCPServerVersion,
        package: dict[str, Any],
        install_path: Path,
        config_values: ConfigValues,
    ) -> MCPRuntimeInstall:
        registry_type = str(package.get("registryType", "")).casefold()
        if registry_type == "pypi":
            return build_pypi_install(server, package, install_path, config_values)
        if registry_type == "uvx":
            return build_uvx_install(server, package, install_path, config_values)
        raise MCPServerInstallationUnsupportedError(
            f"Python package registry is not supported: {registry_type or 'unknown'}"
        )
