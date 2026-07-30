import json
import shlex
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    fingerprint_payload,
    package_runtime,
    secret_environment,
    secret_fingerprint_payload,
    secret_headers,
)
from app.modules.mcp_runtime.providers.kubernetes_client import kubernetes_client_module
from app.modules.mcp_runtime.providers.kubernetes_naming import (
    custom_namespace_annotations,
    custom_namespace_labels,
    hashed_label_value,
    image_pull_secret_names,
    ingress_annotations,
    runtime_ingress_host,
    runtime_installation_identity,
    runtime_object_names,
    safe_kubernetes_name,
)
from app.modules.mcp_runtime.providers.kubernetes_types import (
    KUBERNETES_DNS_LABEL_PATTERN,
    KUBERNETES_GATEWAY_CONTAINER_NAME,
    KUBERNETES_GATEWAY_PORT_NAME,
    KUBERNETES_LABEL_APP_NAME,
    KUBERNETES_LABEL_PART_OF,
    KUBERNETES_MCP_SERVER_CONTAINER_NAME,
    KUBERNETES_METADATA_KEY_NAME_PATTERN,
    KUBERNETES_NPM_PACKAGE_MOUNT_PATH,
    KUBERNETES_NPM_PACKAGE_VOLUME_NAME,
    KUBERNETES_RUNTIME_FILE_MOUNT_PATH,
    KUBERNETES_RUNTIME_FILE_VOLUME_NAME,
    KUBERNETES_RUNTIME_TMP_MOUNT_PATH,
    KUBERNETES_RUNTIME_TMP_VOLUME_NAME,
    KUBERNETES_SUPERGATEWAY_HEALTH_PATH,
    KUBERNETES_SUPERGATEWAY_MCP_PATH,
    WARDN_LABEL_INSTALLATION_ID,
    WARDN_LABEL_ORGANIZATION_ID,
    WARDN_LABEL_RUNTIME_ID,
    WARDN_LABEL_RUNTIME_SESSION_ID,
    WARDN_LABEL_SERVER_NAME,
    WARDN_LABEL_SERVER_VERSION,
    WARDN_LABEL_WORKSPACE_ID,
    WARDN_RUNTIME_APP_NAME,
    KubernetesMetadataError,
    KubernetesReconcileError,
    KubernetesRuntimeManifest,
    KubernetesRuntimeNames,
)

POD_SECURITY_RESTRICTED_LABELS = {
    "pod-security.kubernetes.io/enforce": "restricted",
    "pod-security.kubernetes.io/audit": "restricted",
    "pod-security.kubernetes.io/warn": "restricted",
}
KUBERNETES_NAMESPACE_NAME_LABEL = "kubernetes.io/metadata.name"
KUBE_SYSTEM_NAMESPACE_NAME = "kube-system"
KUBE_DNS_SELECTOR = {"k8s-app": "kube-dns"}
RUNTIME_PUBLIC_EGRESS_EXCEPTIONS = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
]
RUNTIME_SANDBOX_ENVIRONMENT = {
    "HOME": f"{KUBERNETES_RUNTIME_TMP_MOUNT_PATH}/wardn-home",
    "XDG_CACHE_HOME": f"{KUBERNETES_RUNTIME_TMP_MOUNT_PATH}/wardn-cache",
    "UV_CACHE_DIR": f"{KUBERNETES_RUNTIME_TMP_MOUNT_PATH}/wardn-cache/uv",
    "NPM_CONFIG_CACHE": f"{KUBERNETES_RUNTIME_TMP_MOUNT_PATH}/wardn-cache/npm",
}
WARDN_RUNTIME_CONFIG_CHECKSUM_ANNOTATION = "wardn.ai/runtime-config-checksum"
WARDN_RUNTIME_SECRET_CHECKSUM_ANNOTATION = "wardn.ai/runtime-secret-checksum"


def runtime_labels(
    *,
    organization_id: UUID | str | None,
    workspace_id: UUID | str | None,
    installation_id: UUID | str,
    runtime_id: UUID | str,
    runtime_session_id: UUID | str,
    server_name: str,
    server_version: str,
) -> dict[str, str]:
    labels = {
        KUBERNETES_LABEL_APP_NAME: WARDN_RUNTIME_APP_NAME,
        KUBERNETES_LABEL_PART_OF: "wardn",
        WARDN_LABEL_INSTALLATION_ID: str(installation_id),
        WARDN_LABEL_RUNTIME_ID: hashed_label_value("runtime", str(runtime_id)),
        WARDN_LABEL_RUNTIME_SESSION_ID: str(runtime_session_id),
        WARDN_LABEL_SERVER_NAME: hashed_label_value("server", server_name),
        WARDN_LABEL_SERVER_VERSION: hashed_label_value("version", server_version),
    }
    if organization_id:
        labels[WARDN_LABEL_ORGANIZATION_ID] = str(organization_id)
    if workspace_id:
        labels[WARDN_LABEL_WORKSPACE_ID] = str(workspace_id)
    return labels

def validate_label_selector_key(key: str, *, field_name: str) -> None:
    if not key or len(key) > 253:
        raise KubernetesMetadataError(f"{field_name} key must be 1-253 characters")
    if "/" in key:
        prefix, name = key.split("/", 1)
        if not prefix or not name or len(prefix) > 253:
            raise KubernetesMetadataError(f"{field_name} key has invalid DNS prefix")
        if any(
            len(part) > 63 or KUBERNETES_DNS_LABEL_PATTERN.fullmatch(part) is None
            for part in prefix.split(".")
        ):
            raise KubernetesMetadataError(f"{field_name} key has invalid DNS prefix")
    else:
        name = key

    if len(name) > 63 or KUBERNETES_METADATA_KEY_NAME_PATTERN.fullmatch(name) is None:
        raise KubernetesMetadataError(f"{field_name} key has invalid name")

def parse_label_selector_json(
    raw_value: str | dict[str, str],
    *,
    field_name: str,
) -> dict[str, str]:
    if isinstance(raw_value, dict):
        raw_selector = raw_value
    else:
        if not raw_value.strip():
            return {}
        try:
            raw_selector = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise KubernetesMetadataError(f"{field_name} must be valid JSON") from exc

    if not isinstance(raw_selector, dict):
        raise KubernetesMetadataError(f"{field_name} must be a JSON object")

    selector: dict[str, str] = {}
    for key, value in raw_selector.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise KubernetesMetadataError(f"{field_name} keys and values must be strings")
        validate_label_selector_key(key, field_name=field_name)
        if len(value) > 63 or (
            value and KUBERNETES_METADATA_KEY_NAME_PATTERN.fullmatch(value) is None
        ):
            raise KubernetesMetadataError(f"{field_name} value is not a valid label")
        selector[key] = value
    return selector

def control_plane_pod_selector(settings=None) -> dict[str, str]:
    runtime_settings = settings or get_settings()
    return parse_label_selector_json(
        runtime_settings.mcp_runtime_kubernetes_control_plane_pod_selector_json,
        field_name="Kubernetes runtime control-plane pod selector",
    )

def public_egress_ports(settings=None) -> list[int]:
    runtime_settings = settings or get_settings()
    ports = []
    for port in runtime_settings.mcp_runtime_kubernetes_public_egress_ports:
        port_int = int(port)
        if port_int < 1 or port_int > 65_535:
            raise KubernetesMetadataError("Kubernetes runtime public egress ports are invalid")
        if port_int not in ports:
            ports.append(port_int)
    return ports

def runtime_secret_data(
    installation: MCPServerInstallation,
    *,
    settings=None,
) -> dict[str, str]:
    return {
        key: rewrite_runtime_file_path(value, installation.runtime_config or {})
        for key, value in secret_environment(installation).items()
    }

def runtime_file_mounts(runtime_config: dict[str, Any]) -> list[dict[str, str]]:
    mounts = runtime_config.get("fileMounts")
    if not isinstance(mounts, list):
        return []
    normalized = []
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        path = str(mount.get("path") or "").strip()
        mount_path = str(mount.get("mountPath") or "").strip()
        key = str(mount.get("key") or mount.get("name") or "").strip()
        if path and mount_path and key:
            normalized.append(
                {
                    "name": str(mount.get("name") or key),
                    "key": key,
                    "path": path,
                    "mountPath": mount_path,
                }
            )
    return normalized

def runtime_file_secret_key(file_key: str) -> str:
    return f"runtime-file-{safe_kubernetes_name(file_key)}"

def runtime_file_secret_data(installation: MCPServerInstallation) -> dict[str, str]:
    secret_config = installation.secret_references or {}
    files = secret_config.get("files")
    if not isinstance(files, dict):
        return {}
    secret_data = {}
    for name, detail in files.items():
        if not isinstance(detail, dict):
            continue
        key = str(detail.get("key") or name).strip()
        content = detail.get("content")
        if key and content is not None:
            secret_data[runtime_file_secret_key(key)] = str(content)
    return secret_data

def rewrite_runtime_file_path(value: Any, runtime_config: dict[str, Any]) -> str:
    value = str(value)
    for mount in runtime_file_mounts(runtime_config):
        if value == mount["path"]:
            return mount["mountPath"]
    return value

def rewrite_runtime_file_paths(values: list[str], runtime_config: dict[str, Any]) -> list[str]:
    return [rewrite_runtime_file_path(value, runtime_config) for value in values]

def supergateway_stdio_command(installation: MCPServerInstallation) -> str:
    runtime = package_runtime(installation)
    command, args, cwd = kubernetes_runtime_process(runtime, installation.runtime_config or {})
    command_parts = [command, *args]
    if cwd:
        command_parts = ["sh", "-lc", f"cd {shlex.quote(cwd)} && {shlex.join(command_parts)}"]
    return shlex.join(command_parts)

def supergateway_container_args(
    installation: MCPServerInstallation,
    *,
    gateway_port: int,
) -> list[str]:
    return [
        "--stdio",
        supergateway_stdio_command(installation),
        "--outputTransport",
        "streamableHttp",
        "--port",
        str(gateway_port),
        "--streamableHttpPath",
        KUBERNETES_SUPERGATEWAY_MCP_PATH,
        "--healthEndpoint",
        KUBERNETES_SUPERGATEWAY_HEALTH_PATH,
    ]

def runtime_gateway_image_override(runtime_config: dict[str, Any]) -> str:
    for source in (runtime_config, runtime_config.get("package")):
        if not isinstance(source, dict):
            continue
        for field_name in ("gatewayImage", "kubernetesGatewayImage"):
            image = str(source.get(field_name) or "").strip()
            if image:
                return image
    return ""


def supergateway_image(installation: MCPServerInstallation, *, settings=None) -> str:
    runtime_settings = settings or get_settings()
    runtime_config = installation.runtime_config or {}
    override_image = runtime_gateway_image_override(runtime_config)
    if override_image:
        return override_image
    return runtime_settings.mcp_runtime_kubernetes_gateway_image

def normalized_runtime_package_version(value: Any) -> str:
    version = str(value or "").strip()
    if not version or version == "0.0.0":
        return "latest"
    return version

def runtime_package_identifier(runtime_config: dict[str, Any]) -> str:
    package = runtime_config.get("package")
    if not isinstance(package, dict):
        return ""
    return str(package.get("identifier") or "").strip()

def runtime_package_version(runtime_config: dict[str, Any]) -> str:
    package = runtime_config.get("package")
    package_version = package.get("version") if isinstance(package, dict) else ""
    return normalized_runtime_package_version(package_version or runtime_config.get("version"))

def runtime_package_spec(identifier: str, version: str) -> str:
    return identifier if version == "latest" else f"{identifier}@{version}"

def registry_type(runtime_config: dict[str, Any]) -> str:
    return str(runtime_config.get("registryType") or "").strip().lower()

def is_oci_runtime(runtime_config: dict[str, Any]) -> bool:
    return registry_type(runtime_config) == "oci"

def npm_package_binary_name(runtime, runtime_config: dict[str, Any]) -> str:
    command_name = Path(runtime.command).name
    if command_name not in {"node", "npx"}:
        return command_name
    for arg in runtime.args:
        arg_name = Path(str(arg)).name
        if arg_name and arg_name not in {"node", "npx"}:
            return arg_name
    identifier = runtime_package_identifier(runtime_config)
    return identifier.rsplit("/", 1)[-1]

def npm_package_volume_required(runtime_config: dict[str, Any]) -> bool:
    return registry_type(runtime_config) == "npm" and bool(
        runtime_package_identifier(runtime_config)
    )

def npm_package_install_command(runtime_config: dict[str, Any]) -> str:
    identifier = runtime_package_identifier(runtime_config)
    version = runtime_package_version(runtime_config)
    if not identifier:
        raise KubernetesReconcileError("Kubernetes npm runtime package identifier is missing")
    package_spec = runtime_package_spec(identifier, version)
    return shlex.join(
        [
            "npm",
            "install",
            "--omit=dev",
            "--no-audit",
            "--no-fund",
            "--prefix",
            KUBERNETES_NPM_PACKAGE_MOUNT_PATH,
            package_spec,
        ]
    )

def npm_package_volume_mount(client_module: Any | None = None) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1VolumeMount(
        name=KUBERNETES_NPM_PACKAGE_VOLUME_NAME,
        mount_path=KUBERNETES_NPM_PACKAGE_MOUNT_PATH,
    )

def npm_package_volume(client_module: Any | None = None) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Volume(
        name=KUBERNETES_NPM_PACKAGE_VOLUME_NAME,
        empty_dir={},
    )

def runtime_tmp_volume_mount(client_module: Any | None = None) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1VolumeMount(
        name=KUBERNETES_RUNTIME_TMP_VOLUME_NAME,
        mount_path=KUBERNETES_RUNTIME_TMP_MOUNT_PATH,
    )

def runtime_tmp_volume(settings=None, client_module: Any | None = None) -> Any:
    runtime_settings = settings or get_settings()
    client = kubernetes_client_module(client_module)
    size_limit = runtime_settings.mcp_runtime_kubernetes_tmp_size_limit.strip() or None
    return client.V1Volume(
        name=KUBERNETES_RUNTIME_TMP_VOLUME_NAME,
        empty_dir=client.V1EmptyDirVolumeSource(size_limit=size_limit),
    )

def npm_package_init_container(
    *,
    installation: MCPServerInstallation,
    image: str,
    resources: Any | None = None,
    env: list[Any] | None = None,
    security_context: Any | None = None,
    extra_volume_mounts: list[Any] | None = None,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Container(
        name="install-npm-package",
        image=image,
        command=["sh", "-lc"],
        args=[npm_package_install_command(installation.runtime_config or {})],
        env=env or None,
        resources=resources,
        security_context=security_context,
        volume_mounts=[npm_package_volume_mount(client), *(extra_volume_mounts or [])],
    )

def runtime_file_volume_mount(client_module: Any | None = None) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1VolumeMount(
        name=KUBERNETES_RUNTIME_FILE_VOLUME_NAME,
        mount_path=KUBERNETES_RUNTIME_FILE_MOUNT_PATH,
        read_only=True,
    )

def runtime_file_volume(
    *,
    names: KubernetesRuntimeNames,
    file_mounts: list[dict[str, str]],
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Volume(
        name=KUBERNETES_RUNTIME_FILE_VOLUME_NAME,
        secret=client.V1SecretVolumeSource(
            secret_name=names.secret_name,
            items=[
                client.V1KeyToPath(
                    key=runtime_file_secret_key(file_mount["key"]),
                    path=file_mount["key"],
                )
                for file_mount in file_mounts
            ],
        ),
    )

def strip_npm_launcher_args(args: list[str], identifier: str) -> list[str]:
    remaining = list(args)
    if remaining and remaining[0] in {"--offline", "--yes", "-y"}:
        remaining = remaining[1:]
    if remaining and remaining[0] == identifier:
        remaining = remaining[1:]
    return remaining

def stdio_transport_command(transport: Any) -> tuple[str, list[str]]:
    if not isinstance(transport, dict):
        return "", []
    if str(transport.get("type") or "stdio").strip().lower() not in {"", "stdio"}:
        return "", []
    raw_args = transport.get("args")
    args = [str(arg) for arg in raw_args] if isinstance(raw_args, list) else []
    return str(transport.get("command") or "").strip(), args

PYTHON_RUNTIME_DEPENDENCY_FIELDS = ("runtimeDependencies", "pythonDependencies")

def pypi_runtime_dependencies(runtime_config: dict[str, Any]) -> list[str]:
    dependencies: list[str] = []
    sources: list[dict[str, Any]] = [runtime_config]
    package = runtime_config.get("package")
    if isinstance(package, dict):
        sources.append(package)
    for source in sources:
        for field_name in PYTHON_RUNTIME_DEPENDENCY_FIELDS:
            raw_dependencies = source.get(field_name)
            if not isinstance(raw_dependencies, list):
                continue
            for dependency in raw_dependencies:
                value = str(dependency or "").strip()
                if value and value not in dependencies:
                    dependencies.append(value)
    return dependencies

def pypi_runtime_dependency_args(runtime_config: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for dependency in pypi_runtime_dependencies(runtime_config):
        args.extend(["--with", dependency])
    return args


def trim_overlapping_process_args(base_args: list[str], extra_args: list[str]) -> list[str]:
    remaining = list(extra_args)
    max_overlap = min(len(base_args), len(remaining))
    while max_overlap:
        overlap = next(
            (
                size
                for size in range(max_overlap, 0, -1)
                if base_args[-size:] == remaining[:size]
            ),
            0,
        )
        if not overlap:
            break
        remaining = remaining[overlap:]
        max_overlap = min(len(base_args), len(remaining))
    return remaining


def pypi_transport_process_args(
    runtime_config: dict[str, Any],
    *,
    package_spec: str,
    configured_args: list[str],
) -> list[str]:
    package = runtime_config.get("package")
    package_transport = package.get("transport") if isinstance(package, dict) else None
    transport_command, transport_args = stdio_transport_command(
        package_transport or runtime_config.get("transport")
    )
    dependency_args = pypi_runtime_dependency_args(runtime_config)
    transport_command_name = Path(transport_command).name
    configured_args = trim_overlapping_process_args(transport_args, configured_args)
    if transport_command_name == "uvx" and transport_args:
        return ["--from", package_spec, *dependency_args, *transport_args, *configured_args]
    if transport_command_name not in {"", "python", "python3"}:
        return [
            "--from",
            package_spec,
            *dependency_args,
            transport_command_name,
            *transport_args,
            *configured_args,
        ]
    return []


def python_module_invocation(args: list[str]) -> tuple[str, list[str]] | None:
    if len(args) < 2 or args[0] != "-m":
        return None
    module_name = str(args[1]).strip()
    if not module_name:
        return None
    return module_name, args[2:]


def kubernetes_runtime_process(
    runtime,
    runtime_config: dict[str, Any],
) -> tuple[str, list[str], str]:
    package_registry_type = registry_type(runtime_config)
    identifier = runtime_package_identifier(runtime_config)
    version = runtime_package_version(runtime_config)

    if package_registry_type == "uvx":
        return (
            Path(runtime.command).name,
            rewrite_runtime_file_paths(runtime.args, runtime_config),
            "",
        )

    if package_registry_type == "npm" and identifier:
        command_name = Path(runtime.command).name
        if command_name == "node" and runtime.args:
            configured_args = runtime.args[1:]
        elif command_name == "npx":
            configured_args = strip_npm_launcher_args(runtime.args, identifier)
        else:
            configured_args = runtime.args
        binary_name = npm_package_binary_name(runtime, runtime_config)
        binary_path = (
            f"{KUBERNETES_NPM_PACKAGE_MOUNT_PATH}/node_modules/.bin/{binary_name}"
        )
        return binary_path, rewrite_runtime_file_paths(configured_args, runtime_config), ""

    if package_registry_type == "pypi" and identifier:
        package_spec = identifier if version == "latest" else f"{identifier}=={version}"
        module_name = identifier.replace("-", "_")
        configured_args = runtime.args
        declared_module = python_module_invocation(configured_args)
        if declared_module is not None:
            module_name, configured_args = declared_module
        transport_args = pypi_transport_process_args(
            runtime_config,
            package_spec=package_spec,
            configured_args=configured_args,
        )
        if transport_args:
            return (
                "uvx",
                rewrite_runtime_file_paths(transport_args, runtime_config),
                "",
            )
        return (
            "uvx",
            rewrite_runtime_file_paths(
                [
                    "--from",
                    package_spec,
                    *pypi_runtime_dependency_args(runtime_config),
                    "python",
                    "-m",
                    module_name,
                    *configured_args,
                ],
                runtime_config,
            ),
            "",
        )

    return runtime.command, rewrite_runtime_file_paths(runtime.args, runtime_config), runtime.cwd

def oci_runtime_image(runtime_config: dict[str, Any]) -> str:
    for key in ("image", "containerImage"):
        image = str(runtime_config.get(key) or "").strip()
        if image:
            return image
    identifier = runtime_package_identifier(runtime_config)
    if identifier:
        return identifier
    args = runtime_config.get("args")
    if not isinstance(args, list):
        raise KubernetesReconcileError("Kubernetes OCI runtime image is missing")
    image, _ = parse_docker_run_image_and_args([str(arg) for arg in args])
    if not image:
        raise KubernetesReconcileError("Kubernetes OCI runtime image is missing")
    return image

def parse_docker_run_image_and_args(args: list[str]) -> tuple[str, list[str]]:
    remaining = list(args)
    if remaining and remaining[0] == "run":
        remaining = remaining[1:]

    index = 0
    options_with_values = {
        "-e",
        "--env",
        "--env-file",
        "--name",
        "--network",
        "--user",
        "-u",
        "--workdir",
        "-w",
        "--entrypoint",
        "--add-host",
        "-p",
        "--publish",
        "-v",
        "--volume",
    }
    while index < len(remaining):
        arg = remaining[index]
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-"):
            break
        if arg in options_with_values:
            index += 2
            continue
        if any(arg.startswith(f"{option}=") for option in options_with_values):
            index += 1
            continue
        index += 1

    if index >= len(remaining):
        return "", []
    return remaining[index], remaining[index + 1 :]

def replace_flag_value(args: list[str], names: set[str], value: str) -> bool:
    for index, arg in enumerate(args):
        if arg in names:
            if index + 1 < len(args):
                args[index + 1] = value
            else:
                args.append(value)
            return True
        for name in names:
            prefix = f"{name}="
            if arg.startswith(prefix):
                args[index] = f"{name}={value}"
                return True
    return False

def has_flag(args: list[str], names: set[str]) -> bool:
    return any(arg in names or any(arg.startswith(f"{name}=") for name in names) for arg in args)

def package_argument_definitions(runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
    package = runtime_config.get("package")
    if not isinstance(package, dict):
        return []
    package_arguments = package.get("packageArguments")
    if not isinstance(package_arguments, list):
        return []
    return [item for item in package_arguments if isinstance(item, dict)]

def oci_native_http_container_args(runtime_config: dict[str, Any], *, port: int) -> list[str]:
    definitions = package_argument_definitions(runtime_config)
    has_http_command = any(str(item.get("value") or "").strip() == "http" for item in definitions)
    if not has_http_command:
        return []

    flags = {str(item.get("flag") or "").strip() for item in definitions}
    args = ["http"]
    if "--listen-host" in flags:
        args.extend(["--listen-host", "0.0.0.0"])
    elif "--host" in flags:
        args.extend(["--host", "0.0.0.0"])

    if "--port" in flags:
        args.extend(["--port", str(port)])
    elif "-p" in flags and "--publish" not in flags:
        args.extend(["-p", str(port)])
    return args

def oci_runtime_container_args(runtime_config: dict[str, Any], *, port: int) -> list[str]:
    configured_args = runtime_config.get("containerArgs")
    if isinstance(configured_args, list):
        args = [str(arg) for arg in configured_args]
    else:
        docker_args = runtime_config.get("args")
        if not isinstance(docker_args, list):
            args = []
        else:
            _, args = parse_docker_run_image_and_args([str(arg) for arg in docker_args])

    if not args:
        native_http_args = oci_native_http_container_args(runtime_config, port=port)
        if native_http_args:
            return rewrite_runtime_file_paths(native_http_args, runtime_config)

    if has_flag(args, {"--port"}):
        return rewrite_runtime_file_paths(args, runtime_config)
    if not replace_flag_value(args, {"-t", "--transport"}, "streamable-http"):
        args.extend(["-t", "streamable-http"])
    if not has_flag(args, {"-address", "--address"}):
        args.extend(["-address", f"0.0.0.0:{port}"])
    if not has_flag(args, {"-endpoint-path", "--endpoint-path"}):
        args.extend(["-endpoint-path", KUBERNETES_SUPERGATEWAY_MCP_PATH])
    return rewrite_runtime_file_paths(args, runtime_config)

def runtime_request_headers(installation: MCPServerInstallation) -> dict[str, str]:
    headers = secret_headers(installation)
    if "Authorization" in headers:
        return headers

    environment = secret_environment(installation)
    github_token = environment.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers

def build_namespace_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    custom_labels: dict[str, str] | None = None,
    custom_annotations: dict[str, str] | None = None,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    namespace_labels = {
        KUBERNETES_LABEL_PART_OF: "wardn",
        **POD_SECURITY_RESTRICTED_LABELS,
        **labels,
    }
    metadata_labels = custom_labels or {}
    collisions = set(namespace_labels) & set(metadata_labels)
    if collisions:
        raise KubernetesMetadataError(
            f"Kubernetes namespace labels cannot override generated keys: {sorted(collisions)}"
        )
    namespace_labels.update(metadata_labels)
    return client.V1Namespace(
        metadata=client.V1ObjectMeta(
            name=names.namespace,
            labels=namespace_labels,
            annotations=custom_annotations or {},
        )
    )

def build_secret_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    string_data: dict[str, str],
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=names.secret_name,
            namespace=names.namespace,
            labels=labels,
        ),
        type="Opaque",
        string_data=string_data,
    )

def secret_env_vars(
    *,
    names: KubernetesRuntimeNames,
    keys: list[str],
    client_module: Any | None = None,
) -> list[Any]:
    client = kubernetes_client_module(client_module)
    return [
        client.V1EnvVar(
            name=key,
            value_from=client.V1EnvVarSource(
                secret_key_ref=client.V1SecretKeySelector(
                    name=names.secret_name,
                    key=key,
                )
            ),
        )
        for key in sorted(keys)
    ]

def gateway_health_probe(
    *,
    gateway_port_name: str,
    initial_delay_seconds: int = 0,
    failure_threshold: int = 3,
    settings=None,
    client_module: Any | None = None,
) -> Any:
    runtime_settings = settings or get_settings()
    client = kubernetes_client_module(client_module)
    return client.V1Probe(
        http_get=client.V1HTTPGetAction(
            path=KUBERNETES_SUPERGATEWAY_HEALTH_PATH,
            port=gateway_port_name,
        ),
        initial_delay_seconds=max(0, initial_delay_seconds),
        period_seconds=max(1, runtime_settings.mcp_runtime_kubernetes_probe_period_seconds),
        timeout_seconds=max(1, runtime_settings.mcp_runtime_kubernetes_probe_timeout_seconds),
        failure_threshold=max(1, failure_threshold),
    )

def gateway_container_probes(settings=None, client_module: Any | None = None) -> dict[str, Any]:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_probe_enabled:
        return {}
    client = kubernetes_client_module(client_module)
    return {
        "readiness_probe": gateway_health_probe(
            gateway_port_name=KUBERNETES_GATEWAY_PORT_NAME,
            initial_delay_seconds=(
                runtime_settings.mcp_runtime_kubernetes_readiness_initial_delay_seconds
            ),
            failure_threshold=3,
            settings=runtime_settings,
            client_module=client,
        ),
        "liveness_probe": gateway_health_probe(
            gateway_port_name=KUBERNETES_GATEWAY_PORT_NAME,
            initial_delay_seconds=(
                runtime_settings.mcp_runtime_kubernetes_liveness_initial_delay_seconds
            ),
            failure_threshold=3,
            settings=runtime_settings,
            client_module=client,
        ),
        "startup_probe": gateway_health_probe(
            gateway_port_name=KUBERNETES_GATEWAY_PORT_NAME,
            initial_delay_seconds=0,
            failure_threshold=runtime_settings.mcp_runtime_kubernetes_startup_failure_threshold,
            settings=runtime_settings,
            client_module=client,
        ),
    }

def runtime_container_resources(settings=None, client_module: Any | None = None) -> Any:
    runtime_settings = settings or get_settings()
    client = kubernetes_client_module(client_module)
    return client.V1ResourceRequirements(
        requests={
            "cpu": runtime_settings.mcp_runtime_kubernetes_cpu_request,
            "memory": runtime_settings.mcp_runtime_kubernetes_memory_request,
        },
        limits={
            "cpu": runtime_settings.mcp_runtime_kubernetes_cpu_limit,
            "memory": runtime_settings.mcp_runtime_kubernetes_memory_limit,
        },
    )

def runtime_pod_security_context(settings=None, client_module: Any | None = None) -> Any | None:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_sandbox_enabled:
        return None
    client = kubernetes_client_module(client_module)
    run_as_user = runtime_settings.mcp_runtime_kubernetes_run_as_user
    run_as_group = runtime_settings.mcp_runtime_kubernetes_run_as_group
    return client.V1PodSecurityContext(
        run_as_non_root=True,
        run_as_user=run_as_user,
        run_as_group=run_as_group,
        fs_group=run_as_group,
        fs_group_change_policy="OnRootMismatch",
        seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
    )

def runtime_container_security_context(
    settings=None,
    client_module: Any | None = None,
) -> Any | None:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_sandbox_enabled:
        return None
    client = kubernetes_client_module(client_module)
    return client.V1SecurityContext(
        allow_privilege_escalation=False,
        capabilities=client.V1Capabilities(drop=["ALL"]),
        privileged=False,
        proc_mount="Default",
        read_only_root_filesystem=(
            runtime_settings.mcp_runtime_kubernetes_read_only_root_filesystem
        ),
        run_as_non_root=True,
        run_as_user=runtime_settings.mcp_runtime_kubernetes_run_as_user,
        run_as_group=runtime_settings.mcp_runtime_kubernetes_run_as_group,
        seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
    )

def runtime_sandbox_env_vars(client_module: Any | None = None) -> list[Any]:
    client = kubernetes_client_module(client_module)
    return [
        client.V1EnvVar(name=name, value=value)
        for name, value in sorted(RUNTIME_SANDBOX_ENVIRONMENT.items())
    ]


def runtime_rollout_annotations(
    *,
    runtime_session: MCPRuntimeSession,
    secret_data: dict[str, str],
) -> dict[str, str]:
    config_checksum = runtime_session.config_fingerprint or fingerprint_payload(
        {
            "runtimeSessionId": runtime_session.id,
            "installationId": runtime_session.installation_id,
            "serverName": runtime_session.server_name,
            "serverVersion": runtime_session.server_version,
            "runtimeProvider": runtime_session.runtime_provider,
            "runtimeKind": runtime_session.runtime_kind,
        }
    )
    return {
        WARDN_RUNTIME_CONFIG_CHECKSUM_ANNOTATION: config_checksum,
        WARDN_RUNTIME_SECRET_CHECKSUM_ANNOTATION: secret_fingerprint_payload(secret_data),
    }


def build_pod_template_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    annotations: dict[str, str] | None = None,
    secret_keys: list[str],
    container_name: str,
    container_image: str,
    container_port: int,
    container_args: list[str],
    init_containers: list[Any] | None = None,
    volumes: list[Any] | None = None,
    volume_mounts: list[Any] | None = None,
    enable_health_probes: bool = True,
    image_pull_secret_names: list[str] | None = None,
    settings=None,
    client_module: Any | None = None,
) -> Any:
    runtime_settings = settings or get_settings()
    client = kubernetes_client_module(client_module)
    resources = runtime_container_resources(runtime_settings, client_module=client)
    pod_security_context = runtime_pod_security_context(runtime_settings, client_module=client)
    container_security_context = runtime_container_security_context(
        runtime_settings,
        client_module=client,
    )
    sandbox_env_vars = runtime_sandbox_env_vars(client)
    image_pull_secrets = [
        client.V1LocalObjectReference(name=name)
        for name in (image_pull_secret_names or [])
    ]
    for init_container in init_containers or []:
        if getattr(init_container, "resources", None) is None:
            init_container.resources = resources
        if getattr(init_container, "security_context", None) is None:
            init_container.security_context = container_security_context
    return client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(
            name=names.pod_name,
            namespace=names.namespace,
            labels=labels,
            annotations=annotations or {},
        ),
        spec=client.V1PodSpec(
            automount_service_account_token=False,
            enable_service_links=False,
            host_ipc=False,
            host_network=False,
            host_pid=False,
            security_context=pod_security_context,
            image_pull_secrets=image_pull_secrets or None,
            init_containers=init_containers or None,
            restart_policy="Always",
            runtime_class_name=(
                runtime_settings.mcp_runtime_kubernetes_runtime_class_name.strip() or None
            ),
            volumes=volumes or None,
            containers=[
                client.V1Container(
                    name=container_name,
                    image=container_image,
                    args=container_args,
                    ports=[
                        client.V1ContainerPort(
                            container_port=container_port,
                            name=KUBERNETES_GATEWAY_PORT_NAME,
                        )
                    ],
                    env=[
                        *sandbox_env_vars,
                        *secret_env_vars(
                            names=names,
                            keys=secret_keys,
                            client_module=client,
                        ),
                    ],
                    resources=resources,
                    security_context=container_security_context,
                    volume_mounts=volume_mounts or None,
                    **(
                        gateway_container_probes(runtime_settings, client_module=client)
                        if enable_health_probes
                        else {}
                    ),
                )
            ],
        ),
    )

def service_selector(labels: dict[str, str]) -> dict[str, str]:
    return {
        KUBERNETES_LABEL_APP_NAME: labels[KUBERNETES_LABEL_APP_NAME],
        WARDN_LABEL_RUNTIME_ID: labels[WARDN_LABEL_RUNTIME_ID],
    }

def runtime_workload_labels(labels: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in labels.items()
        if key != WARDN_LABEL_RUNTIME_SESSION_ID
    }

def build_deployment_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    pod_template: Any,
    replicas: int = 1,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=names.pod_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1DeploymentSpec(
            replicas=replicas,
            selector=client.V1LabelSelector(match_labels=service_selector(labels)),
            template=pod_template,
        ),
    )

def build_service_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    gateway_port: int,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=names.service_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1ServiceSpec(
            type="ClusterIP",
            selector=service_selector(labels),
            ports=[
                client.V1ServicePort(
                    name=KUBERNETES_GATEWAY_PORT_NAME,
                    port=gateway_port,
                    target_port=gateway_port,
                )
            ],
        ),
    )

def runtime_network_policy_names(names: KubernetesRuntimeNames) -> tuple[str, str, str, str]:
    return (
        safe_kubernetes_name(f"{names.pod_name}-default-deny"),
        safe_kubernetes_name(f"{names.pod_name}-allow-wardn-ingress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-dns-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-public-egress"),
    )

def label_selector(labels: dict[str, str] | None, client_module: Any | None = None) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1LabelSelector(match_labels=labels or {})

def namespace_name_selector(namespace: str, *, client_module: Any | None = None) -> Any:
    namespace_name = namespace.strip()
    if KUBERNETES_DNS_LABEL_PATTERN.fullmatch(namespace_name) is None:
        raise KubernetesMetadataError(
            "Kubernetes runtime control-plane namespace must be a valid namespace name"
        )
    return label_selector(
        {KUBERNETES_NAMESPACE_NAME_LABEL: namespace_name},
        client_module=client_module,
    )

def build_default_deny_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name=policy_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=label_selector({}, client),
            policy_types=["Ingress", "Egress"],
            ingress=[],
            egress=[],
        ),
    )

def build_runtime_ingress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    gateway_port: int,
    settings=None,
    client_module: Any | None = None,
) -> Any:
    runtime_settings = settings or get_settings()
    client = kubernetes_client_module(client_module)
    source_pod_selector = control_plane_pod_selector(runtime_settings)
    return client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name=policy_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=label_selector(service_selector(labels), client),
            policy_types=["Ingress"],
            ingress=[
                client.V1NetworkPolicyIngressRule(
                    _from=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=namespace_name_selector(
                                runtime_settings.mcp_runtime_kubernetes_control_plane_namespace,
                                client_module=client,
                            ),
                            pod_selector=(
                                label_selector(source_pod_selector, client)
                                if source_pod_selector
                                else None
                            ),
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(
                            protocol="TCP",
                            port=gateway_port,
                        )
                    ],
                )
            ],
        ),
    )

def build_dns_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name=policy_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=label_selector(service_selector(labels), client),
            policy_types=["Egress"],
            egress=[
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=namespace_name_selector(
                                KUBE_SYSTEM_NAMESPACE_NAME,
                                client_module=client,
                            ),
                            pod_selector=label_selector(KUBE_DNS_SELECTOR, client),
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(protocol="UDP", port=53),
                        client.V1NetworkPolicyPort(protocol="TCP", port=53),
                    ],
                )
            ],
        ),
    )

def build_public_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    settings=None,
    client_module: Any | None = None,
) -> Any:
    runtime_settings = settings or get_settings()
    client = kubernetes_client_module(client_module)
    return client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name=policy_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=label_selector(service_selector(labels), client),
            policy_types=["Egress"],
            egress=[
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            ip_block=client.V1IPBlock(
                                cidr="0.0.0.0/0",
                                _except=RUNTIME_PUBLIC_EGRESS_EXCEPTIONS,
                            )
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(protocol="TCP", port=port)
                        for port in public_egress_ports(runtime_settings)
                    ],
                )
            ],
        ),
    )

def build_network_policy_manifests(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    gateway_port: int,
    settings=None,
    client_module: Any | None = None,
) -> list[Any]:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_network_policy_enabled:
        return []
    policy_names = runtime_network_policy_names(names)
    client = kubernetes_client_module(client_module)
    policies = [
        build_default_deny_network_policy(
            names=names,
            labels=labels,
            policy_name=policy_names[0],
            client_module=client,
        ),
        build_runtime_ingress_network_policy(
            names=names,
            labels=labels,
            policy_name=policy_names[1],
            gateway_port=gateway_port,
            settings=runtime_settings,
            client_module=client,
        ),
        build_dns_egress_network_policy(
            names=names,
            labels=labels,
            policy_name=policy_names[2],
            client_module=client,
        ),
    ]
    if runtime_settings.mcp_runtime_kubernetes_allow_public_egress:
        policies.append(
            build_public_egress_network_policy(
                names=names,
                labels=labels,
                policy_name=policy_names[3],
                settings=runtime_settings,
                client_module=client,
            )
        )
    return policies

def build_ingress_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    gateway_port: int,
    settings=None,
    client_module: Any | None = None,
) -> Any | None:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_ingress_enabled:
        return None

    client = kubernetes_client_module(client_module)
    host = runtime_ingress_host(names, runtime_settings)
    tls_secret_name = runtime_settings.mcp_runtime_kubernetes_ingress_tls_secret_name.strip()
    tls = [
        client.V1IngressTLS(
            hosts=[host],
            secret_name=tls_secret_name,
        )
    ] if tls_secret_name else None
    ingress_class_name = (
        runtime_settings.mcp_runtime_kubernetes_ingress_class_name.strip() or None
    )
    return client.V1Ingress(
        metadata=client.V1ObjectMeta(
            name=names.ingress_name,
            namespace=names.namespace,
            labels=labels,
            annotations=ingress_annotations(host=host, settings=runtime_settings),
        ),
        spec=client.V1IngressSpec(
            ingress_class_name=ingress_class_name,
            tls=tls,
            rules=[
                client.V1IngressRule(
                    host=host,
                    http=client.V1HTTPIngressRuleValue(
                        paths=[
                            client.V1HTTPIngressPath(
                                path="/",
                                path_type="Prefix",
                                backend=client.V1IngressBackend(
                                    service=client.V1IngressServiceBackend(
                                        name=names.service_name,
                                        port=client.V1ServiceBackendPort(
                                            number=gateway_port,
                                        ),
                                    ),
                                ),
                            )
                        ],
                    ),
                )
            ],
        ),
    )

def build_runtime_manifests(
    installation: MCPServerInstallation,
    runtime_session: MCPRuntimeSession,
    *,
    settings=None,
    client_module: Any | None = None,
) -> KubernetesRuntimeManifest:
    runtime_settings = settings or get_settings()
    runtime_id = runtime_installation_identity(installation)
    names = runtime_object_names(
        runtime_id=runtime_id,
        server_name=installation.server_name,
        config_name=installation.config_name,
        organization_id=runtime_session.organization_id,
        workspace_id=runtime_session.workspace_id,
        prefix=runtime_settings.mcp_runtime_kubernetes_namespace_prefix,
    )
    labels = runtime_labels(
        organization_id=runtime_session.organization_id,
        workspace_id=runtime_session.workspace_id,
        installation_id=runtime_session.installation_id,
        runtime_id=runtime_id,
        runtime_session_id=runtime_session.id,
        server_name=runtime_session.server_name,
        server_version=runtime_session.server_version,
    )
    secret_env_data = runtime_secret_data(installation, settings=runtime_settings)
    secret_file_data = runtime_file_secret_data(installation)
    secret_data = {**secret_env_data, **secret_file_data}
    client = kubernetes_client_module(client_module)
    namespace_labels = custom_namespace_labels(runtime_settings)
    namespace_annotations = custom_namespace_annotations(runtime_settings)
    pull_secret_names = image_pull_secret_names(runtime_settings)
    workload_labels = runtime_workload_labels(labels)
    runtime_config = installation.runtime_config or {}
    file_mounts = runtime_file_mounts(runtime_config)
    container_name = KUBERNETES_GATEWAY_CONTAINER_NAME
    container_image = ""
    container_args: list[str] = []
    health_path: str | None = KUBERNETES_SUPERGATEWAY_HEALTH_PATH
    package_volumes = [runtime_tmp_volume(runtime_settings, client_module=client)]
    package_volume_mounts = [runtime_tmp_volume_mount(client)]
    init_containers = []
    if file_mounts:
        package_volumes.append(
            runtime_file_volume(
                names=names,
                file_mounts=file_mounts,
                client_module=client,
            )
        )
        package_volume_mounts.append(runtime_file_volume_mount(client))
    if is_oci_runtime(runtime_config):
        container_name = KUBERNETES_MCP_SERVER_CONTAINER_NAME
        container_image = oci_runtime_image(runtime_config)
        container_args = oci_runtime_container_args(
            runtime_config,
            port=runtime_settings.mcp_runtime_kubernetes_service_port,
        )
        health_path = None
    else:
        container_image = supergateway_image(installation, settings=runtime_settings)
        container_args = supergateway_container_args(
            installation,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
        )
        if npm_package_volume_required(runtime_config):
            package_volumes.append(npm_package_volume(client))
            package_volume_mounts.append(npm_package_volume_mount(client))
            init_containers.append(
                npm_package_init_container(
                    installation=installation,
                    image=container_image,
                    resources=runtime_container_resources(
                        runtime_settings,
                        client_module=client,
                    ),
                    env=runtime_sandbox_env_vars(client),
                    security_context=runtime_container_security_context(
                        runtime_settings,
                        client_module=client,
                    ),
                    extra_volume_mounts=[runtime_tmp_volume_mount(client)],
                    client_module=client,
                )
            )
    pod_template = build_pod_template_manifest(
        names=names,
        labels=workload_labels,
        annotations=runtime_rollout_annotations(
            runtime_session=runtime_session,
            secret_data=secret_data,
        ),
        secret_keys=list(secret_env_data),
        container_name=container_name,
        container_image=container_image,
        container_port=runtime_settings.mcp_runtime_kubernetes_service_port,
        container_args=container_args,
        init_containers=init_containers,
        volumes=package_volumes,
        volume_mounts=package_volume_mounts,
        enable_health_probes=health_path is not None,
        image_pull_secret_names=pull_secret_names,
        settings=runtime_settings,
        client_module=client,
    )
    return KubernetesRuntimeManifest(
        names=names,
        labels=labels,
        secret_data=secret_data,
        secret_env_keys=list(secret_env_data),
        namespace=build_namespace_manifest(
            names=names,
            labels=labels,
            custom_labels=namespace_labels,
            custom_annotations=namespace_annotations,
            client_module=client,
        ),
        secret=build_secret_manifest(
            names=names,
            labels=labels,
            string_data=secret_data,
            client_module=client,
        ),
        pod=pod_template,
        deployment=build_deployment_manifest(
            names=names,
            labels=labels,
            pod_template=pod_template,
            replicas=1,
            client_module=client,
        ),
        service=build_service_manifest(
            names=names,
            labels=labels,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            client_module=client,
        ),
        network_policies=build_network_policy_manifests(
            names=names,
            labels=labels,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            settings=runtime_settings,
            client_module=client,
        ),
        ingress=build_ingress_manifest(
            names=names,
            labels=labels,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            settings=runtime_settings,
            client_module=client,
        ),
        health_path=health_path,
    )
