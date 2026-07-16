import shlex
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import package_runtime, secret_environment, secret_headers
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
    KUBERNETES_GATEWAY_CONTAINER_NAME,
    KUBERNETES_GATEWAY_PORT_NAME,
    KUBERNETES_LABEL_APP_NAME,
    KUBERNETES_LABEL_PART_OF,
    KUBERNETES_MCP_SERVER_CONTAINER_NAME,
    KUBERNETES_NPM_PACKAGE_MOUNT_PATH,
    KUBERNETES_NPM_PACKAGE_VOLUME_NAME,
    KUBERNETES_RUNTIME_FILE_MOUNT_PATH,
    KUBERNETES_RUNTIME_FILE_VOLUME_NAME,
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

def supergateway_image(installation: MCPServerInstallation, *, settings=None) -> str:
    runtime_settings = settings or get_settings()
    runtime_config = installation.runtime_config or {}
    package_registry_type = registry_type(runtime_config)
    command_name = Path(package_runtime(installation).command).name
    if package_registry_type in {"uvx", "pypi"} or command_name == "uvx":
        return runtime_settings.mcp_runtime_kubernetes_gateway_uvx_image
    if package_registry_type == "deno" or command_name == "deno":
        return runtime_settings.mcp_runtime_kubernetes_gateway_deno_image
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

def npm_package_init_container(
    *,
    installation: MCPServerInstallation,
    image: str,
    resources: Any | None = None,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Container(
        name="install-npm-package",
        image=image,
        command=["sh", "-lc"],
        args=[npm_package_install_command(installation.runtime_config or {})],
        resources=resources,
        volume_mounts=[npm_package_volume_mount(client)],
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
        if len(configured_args) >= 2 and configured_args[:2] == ["-m", module_name]:
            configured_args = configured_args[2:]
        return (
            "uvx",
            rewrite_runtime_file_paths(
                ["--from", package_spec, "python", "-m", module_name, *configured_args],
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

def build_pod_template_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
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
    image_pull_secrets = [
        client.V1LocalObjectReference(name=name)
        for name in (image_pull_secret_names or [])
    ]
    for init_container in init_containers or []:
        if getattr(init_container, "resources", None) is None:
            init_container.resources = resources
    return client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(
            name=names.pod_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1PodSpec(
            automount_service_account_token=False,
            image_pull_secrets=image_pull_secrets or None,
            init_containers=init_containers or None,
            restart_policy="Always",
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
                        *secret_env_vars(
                            names=names,
                            keys=secret_keys,
                            client_module=client,
                        ),
                    ],
                    resources=resources,
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
    package_volumes = []
    package_volume_mounts = []
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
                    client_module=client,
                )
            )
    pod_template = build_pod_template_manifest(
        names=names,
        labels=workload_labels,
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
        ingress=build_ingress_manifest(
            names=names,
            labels=labels,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            settings=runtime_settings,
            client_module=client,
        ),
        health_path=health_path,
    )
