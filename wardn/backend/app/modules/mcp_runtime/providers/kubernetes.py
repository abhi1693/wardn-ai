import hashlib
import importlib
import json
import re
import shlex
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException as HTTPClientException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from app.core.config import get_settings
from app.modules.mcp_gateway import client as mcp_client
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_HEALTH_NOT_READY,
    RUNTIME_HEALTH_READY,
    RUNTIME_HEALTH_STOPPED,
    RUNTIME_KIND_PACKAGE,
    RUNTIME_PROVIDER_KUBERNETES,
    RUNTIME_TRANSPORT_STREAMABLE_HTTP,
    RuntimeHealth,
    RuntimeSpec,
    fingerprint_payload,
    package_runtime,
    runtime_kind,
    secret_environment,
    secret_fingerprint_payload,
    secret_headers,
)

KUBERNETES_LABEL_APP_NAME = "app.kubernetes.io/name"
KUBERNETES_LABEL_PART_OF = "app.kubernetes.io/part-of"
WARDN_LABEL_ORGANIZATION_ID = "wardn.ai/organization-id"
WARDN_LABEL_WORKSPACE_ID = "wardn.ai/workspace-id"
WARDN_LABEL_INSTALLATION_ID = "wardn.ai/installation-id"
WARDN_LABEL_RUNTIME_ID = "wardn.ai/runtime-id"
WARDN_LABEL_RUNTIME_SESSION_ID = "wardn.ai/runtime-session-id"
WARDN_LABEL_SERVER_NAME = "wardn.ai/server-name"
WARDN_LABEL_SERVER_VERSION = "wardn.ai/server-version"
WARDN_RUNTIME_APP_NAME = "wardn-mcp-runtime"
KUBERNETES_NAME_MAX_LENGTH = 63
KUBERNETES_LABEL_VALUE_MAX_LENGTH = 63
KUBERNETES_GATEWAY_CONTAINER_NAME = "supergateway"
KUBERNETES_MCP_SERVER_CONTAINER_NAME = "mcp-server"
KUBERNETES_GATEWAY_PORT_NAME = "http"
KUBERNETES_SUPERGATEWAY_MCP_PATH = "/mcp"
KUBERNETES_SUPERGATEWAY_HEALTH_PATH = "/healthz"
KUBERNETES_NPM_PACKAGE_VOLUME_NAME = "npm-package"
KUBERNETES_NPM_PACKAGE_MOUNT_PATH = "/opt/wardn/npm-package"
KUBERNETES_RUNTIME_FILE_VOLUME_NAME = "runtime-files"
KUBERNETES_RUNTIME_FILE_MOUNT_PATH = "/opt/wardn/runtime-files"
KUBERNETES_API_CONNECT_TIMEOUT_SECONDS = 5
KUBERNETES_API_READ_TIMEOUT_SECONDS = 10
KUBERNETES_METADATA_KEY_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?$"
)
KUBERNETES_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
KUBERNETES_RESERVED_METADATA_KEYS = {
    KUBERNETES_LABEL_APP_NAME,
    KUBERNETES_LABEL_PART_OF,
}
KUBERNETES_RESERVED_METADATA_PREFIXES = (
    "wardn.ai/",
    "kubernetes.io/",
    "k8s.io/",
)


class KubernetesRuntimeProviderError(RuntimeError):
    pass


class KubernetesConfigError(KubernetesRuntimeProviderError):
    pass


class KubernetesReconcileError(KubernetesRuntimeProviderError):
    pass


class KubernetesRuntimeNotReadyError(KubernetesRuntimeProviderError):
    pass


class KubernetesMetadataError(KubernetesRuntimeProviderError):
    pass


class KubernetesImagePullSecretError(KubernetesRuntimeProviderError):
    pass


class KubernetesIngressError(KubernetesRuntimeProviderError):
    pass


@dataclass(frozen=True)
class KubernetesClientSet:
    core_v1: Any
    apps_v1: Any
    networking_v1: Any
    loaded_config: str


@dataclass(frozen=True)
class KubernetesRuntimeNames:
    namespace: str
    pod_name: str
    service_name: str
    secret_name: str
    ingress_name: str


@dataclass(frozen=True)
class KubernetesRuntimeManifest:
    names: KubernetesRuntimeNames
    labels: dict[str, str]
    secret_data: dict[str, str]
    secret_env_keys: list[str]
    namespace: Any
    secret: Any
    pod: Any
    deployment: Any
    service: Any
    ingress: Any | None = None
    health_path: str | None = KUBERNETES_SUPERGATEWAY_HEALTH_PATH


@dataclass(frozen=True)
class KubernetesReconcileResult:
    endpoint_url: str
    pod: Any | None = None
    gateway_status: dict[str, Any] | None = None


class KubernetesClientFactory:
    def __init__(
        self,
        *,
        settings=None,
        config_module: Any | None = None,
        client_module: Any | None = None,
    ) -> None:
        self._settings = settings
        self._config_module = config_module
        self._client_module = client_module

    @property
    def settings(self):
        return self._settings or get_settings()

    def load(self) -> KubernetesClientSet:
        loaded_config = self.load_config()
        client_module = self._client_module or importlib.import_module("kubernetes.client")
        return KubernetesClientSet(
            core_v1=client_module.CoreV1Api(),
            apps_v1=client_module.AppsV1Api(),
            networking_v1=client_module.NetworkingV1Api(),
            loaded_config=loaded_config,
        )

    def load_config(self) -> str:
        config_module = self._config_module or importlib.import_module("kubernetes.config")
        try:
            config_module.load_incluster_config()
            return "in_cluster"
        except Exception as incluster_exc:
            if not self.settings.mcp_runtime_kubernetes_allow_kubeconfig:
                raise KubernetesConfigError(
                    "Kubernetes in-cluster config is unavailable and kubeconfig fallback is "
                    "disabled"
                ) from incluster_exc

        kwargs: dict[str, str] = {}
        if self.settings.mcp_runtime_kubernetes_kubeconfig_path:
            kwargs["config_file"] = self.settings.mcp_runtime_kubernetes_kubeconfig_path
        if self.settings.mcp_runtime_kubernetes_context:
            kwargs["context"] = self.settings.mcp_runtime_kubernetes_context

        try:
            config_module.load_kube_config(**kwargs)
        except Exception as kubeconfig_exc:
            raise KubernetesConfigError(
                "Kubernetes kubeconfig could not be loaded"
            ) from kubeconfig_exc
        return "kubeconfig"

    def api_exception_class(self) -> type[Exception]:
        client_module = self._client_module or importlib.import_module("kubernetes.client")
        return client_module.ApiException


def short_hash(value: str, *, length: int = 10) -> str:
    return hashlib.blake2s(value.encode("utf-8"), digest_size=8).hexdigest()[:length]


def safe_kubernetes_name(value: str, *, max_length: int = KUBERNETES_NAME_MAX_LENGTH) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    normalized = re.sub(r"-+", "-", normalized) or "runtime"
    if len(normalized) <= max_length:
        return normalized
    suffix = short_hash(value, length=8)
    return f"{normalized[: max_length - len(suffix) - 1].strip('-')}-{suffix}"


def safe_label_value(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("._-")
    normalized = re.sub(r"-+", "-", normalized) or "value"
    if len(normalized) <= KUBERNETES_LABEL_VALUE_MAX_LENGTH:
        return normalized
    suffix = short_hash(value, length=8)
    prefix = normalized[: KUBERNETES_LABEL_VALUE_MAX_LENGTH - len(suffix) - 1].strip(
        "._-"
    )
    return f"{prefix}-{suffix}"


def hashed_label_value(prefix: str, value: str) -> str:
    return safe_label_value(f"{prefix}-{short_hash(value, length=12)}")


def metadata_key_is_reserved(key: str) -> bool:
    return key in KUBERNETES_RESERVED_METADATA_KEYS or key.startswith(
        KUBERNETES_RESERVED_METADATA_PREFIXES
    )


def validate_metadata_key(key: str, *, field_name: str) -> None:
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
    if metadata_key_is_reserved(key):
        raise KubernetesMetadataError(f"{field_name} key is reserved: {key}")


def validate_dns_subdomain_name(value: str, *, field_name: str) -> None:
    if not value or len(value) > 253:
        raise KubernetesImagePullSecretError(f"{field_name} must be 1-253 characters")
    if any(
        len(part) > 63 or KUBERNETES_DNS_LABEL_PATTERN.fullmatch(part) is None
        for part in value.split(".")
    ):
        raise KubernetesImagePullSecretError(
            f"{field_name} must be a valid Kubernetes DNS subdomain name"
        )


def validate_label_value(value: str, *, field_name: str) -> None:
    if len(value) > KUBERNETES_LABEL_VALUE_MAX_LENGTH:
        raise KubernetesMetadataError(f"{field_name} value must be 63 characters or fewer")
    if value and KUBERNETES_METADATA_KEY_NAME_PATTERN.fullmatch(value) is None:
        raise KubernetesMetadataError(f"{field_name} value is not a valid Kubernetes label")


def parse_metadata_json(raw_value: str | dict[str, str], *, field_name: str) -> dict[str, str]:
    if isinstance(raw_value, dict):
        raw_metadata = raw_value
    else:
        if not raw_value.strip():
            return {}
        try:
            raw_metadata = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise KubernetesMetadataError(f"{field_name} must be valid JSON") from exc

    if not isinstance(raw_metadata, dict):
        raise KubernetesMetadataError(f"{field_name} must be a JSON object")

    metadata: dict[str, str] = {}
    for key, value in raw_metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise KubernetesMetadataError(f"{field_name} keys and values must be strings")
        validate_metadata_key(key, field_name=field_name)
        metadata[key] = value
    return metadata


def custom_namespace_labels(settings=None) -> dict[str, str]:
    runtime_settings = settings or get_settings()
    labels = parse_metadata_json(
        runtime_settings.mcp_runtime_kubernetes_namespace_labels_json,
        field_name="Kubernetes namespace label",
    )
    for value in labels.values():
        validate_label_value(value, field_name="Kubernetes namespace label")
    return labels


def custom_namespace_annotations(settings=None) -> dict[str, str]:
    runtime_settings = settings or get_settings()
    annotations = parse_metadata_json(
        runtime_settings.mcp_runtime_kubernetes_namespace_annotations_json,
        field_name="Kubernetes namespace annotation",
    )
    for value in annotations.values():
        if len(value) > 262_144:
            raise KubernetesMetadataError(
                "Kubernetes namespace annotation value must be 262144 characters or fewer"
            )
    return annotations


def image_pull_secret_names(settings=None) -> list[str]:
    runtime_settings = settings or get_settings()
    name = runtime_settings.mcp_runtime_kubernetes_image_pull_secret_name.strip()
    if not name:
        return []
    validate_dns_subdomain_name(name, field_name="Kubernetes image pull secret name")
    return [name]


def validate_ingress_scheme(value: str) -> str:
    scheme = value.strip().lower()
    if scheme not in {"http", "https"}:
        raise KubernetesIngressError("Kubernetes runtime ingress scheme must be http or https")
    return scheme


def validate_ingress_base_domain(value: str) -> str:
    base_domain = value.strip().lower().strip(".")
    if not base_domain:
        raise KubernetesIngressError(
            "Kubernetes runtime ingress base domain is required when ingress is enabled"
        )
    try:
        validate_dns_subdomain_name(
            base_domain,
            field_name="Kubernetes runtime ingress base domain",
        )
    except KubernetesImagePullSecretError as exc:
        raise KubernetesIngressError(str(exc)) from exc
    return base_domain


def custom_ingress_annotations(settings=None) -> dict[str, str]:
    runtime_settings = settings or get_settings()
    annotations = parse_metadata_json(
        runtime_settings.mcp_runtime_kubernetes_ingress_annotations_json,
        field_name="Kubernetes ingress annotation",
    )
    for value in annotations.values():
        if len(value) > 262_144:
            raise KubernetesMetadataError(
                "Kubernetes ingress annotation value must be 262144 characters or fewer"
            )
    return annotations


def runtime_ingress_host(names: KubernetesRuntimeNames, settings=None) -> str:
    runtime_settings = settings or get_settings()
    base_domain = validate_ingress_base_domain(
        runtime_settings.mcp_runtime_kubernetes_ingress_base_domain
    )
    return f"{names.pod_name}.{base_domain}"


def runtime_ingress_endpoint_url(
    *,
    names: KubernetesRuntimeNames,
    settings=None,
) -> str:
    runtime_settings = settings or get_settings()
    scheme = validate_ingress_scheme(runtime_settings.mcp_runtime_kubernetes_ingress_scheme)
    host = runtime_ingress_host(names, runtime_settings)
    return f"{scheme}://{host}{KUBERNETES_SUPERGATEWAY_MCP_PATH}"


def ingress_annotations(
    *,
    host: str,
    settings=None,
) -> dict[str, str]:
    runtime_settings = settings or get_settings()
    annotations: dict[str, str] = {}
    ingress_class_name = runtime_settings.mcp_runtime_kubernetes_ingress_class_name.strip()
    if ingress_class_name:
        annotations["kubernetes.io/ingress.class"] = ingress_class_name
    entrypoints = runtime_settings.mcp_runtime_kubernetes_ingress_traefik_entrypoints.strip()
    if entrypoints:
        annotations["traefik.ingress.kubernetes.io/router.entrypoints"] = entrypoints
    if validate_ingress_scheme(runtime_settings.mcp_runtime_kubernetes_ingress_scheme) == "https":
        annotations["traefik.ingress.kubernetes.io/router.tls"] = "true"
    if runtime_settings.mcp_runtime_kubernetes_ingress_external_dns_enabled:
        annotations["external-dns.alpha.kubernetes.io/hostname"] = host
    annotations.update(custom_ingress_annotations(runtime_settings))
    return annotations


def kubernetes_client_module(client_module: Any | None = None) -> Any:
    return client_module or importlib.import_module("kubernetes.client")


def runtime_namespace_name(
    *,
    organization_id: UUID | str | None,
    workspace_id: UUID | str | None,
    prefix: str | None = None,
) -> str:
    namespace_prefix = safe_kubernetes_name(
        prefix or get_settings().mcp_runtime_kubernetes_namespace_prefix
    )
    if workspace_id:
        workspace_hash = short_hash(str(workspace_id))
        if organization_id:
            organization_hash = short_hash(str(organization_id))
            return safe_kubernetes_name(
                f"{namespace_prefix}-org-{organization_hash}-ws-{workspace_hash}"
            )
        return safe_kubernetes_name(f"{namespace_prefix}-ws-{workspace_hash}")
    if organization_id:
        return safe_kubernetes_name(f"{namespace_prefix}-org-{short_hash(str(organization_id))}")
    return safe_kubernetes_name(f"{namespace_prefix}-runtime")


def runtime_object_names(
    *,
    server_name: str = "",
    config_name: str = "",
    runtime_id: UUID | str | None = None,
    runtime_session_id: UUID | str | None = None,
    organization_id: UUID | str | None,
    workspace_id: UUID | str | None,
    prefix: str | None = None,
) -> KubernetesRuntimeNames:
    if server_name:
        base_name = runtime_object_base_name(
            server_name=server_name,
            config_name=config_name,
        )
    else:
        object_id = runtime_id or runtime_session_id
        if object_id is None:
            raise KubernetesReconcileError("Kubernetes runtime object identity is missing")
        runtime_hash = short_hash(str(object_id), length=12)
        base_name = safe_kubernetes_name(f"mcp-{runtime_hash}")
    return KubernetesRuntimeNames(
        namespace=runtime_namespace_name(
            organization_id=organization_id,
            workspace_id=workspace_id,
            prefix=prefix,
        ),
        pod_name=base_name,
        service_name=safe_kubernetes_name(f"{base_name}-svc"),
        secret_name=safe_kubernetes_name(f"{base_name}-secret"),
        ingress_name=safe_kubernetes_name(f"{base_name}-ing"),
    )


def runtime_object_base_name(*, server_name: str, config_name: str) -> str:
    instance_name = config_name or "default"
    return safe_kubernetes_name(f"{server_name}-{instance_name}")


def runtime_installation_identity(installation: MCPServerInstallation) -> str:
    return f"{installation.server_name}:{installation.config_name or 'default'}"


def runtime_object_identity(runtime_session: MCPRuntimeSession) -> str:
    return runtime_session.config_fingerprint or str(runtime_session.id)


def runtime_object_names_for_session(
    runtime_session: MCPRuntimeSession,
    *,
    prefer_stored_names: bool = False,
    settings=None,
) -> KubernetesRuntimeNames:
    runtime_settings = settings or get_settings()
    names = runtime_object_names(
        runtime_id=runtime_object_identity(runtime_session),
        server_name=runtime_session.server_name,
        config_name="",
        organization_id=runtime_session.organization_id,
        workspace_id=runtime_session.workspace_id,
        prefix=runtime_settings.mcp_runtime_kubernetes_namespace_prefix,
    )
    if prefer_stored_names and runtime_session.pod_name:
        pod_name = runtime_session.pod_name
        service_name = safe_kubernetes_name(f"{pod_name}-svc")
        secret_name = safe_kubernetes_name(f"{pod_name}-secret")
        ingress_name = safe_kubernetes_name(f"{pod_name}-ing")
    else:
        pod_name = names.pod_name
        service_name = names.service_name
        secret_name = names.secret_name
        ingress_name = names.ingress_name
    return KubernetesRuntimeNames(
        namespace=runtime_session.namespace or names.namespace,
        pod_name=pod_name,
        service_name=service_name,
        secret_name=secret_name,
        ingress_name=ingress_name,
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


def runtime_service_endpoint_url(
    *,
    names: KubernetesRuntimeNames,
    gateway_port: int,
) -> str:
    return (
        f"http://{names.service_name}.{names.namespace}.svc.cluster.local:"
        f"{gateway_port}{KUBERNETES_SUPERGATEWAY_MCP_PATH}"
    )


def runtime_health_endpoint_url(endpoint_url: str) -> str:
    return endpoint_url.removesuffix(KUBERNETES_SUPERGATEWAY_MCP_PATH) + (
        KUBERNETES_SUPERGATEWAY_HEALTH_PATH
    )


def get_gateway_health(
    endpoint_url: str,
    *,
    timeout: float = 5,
    verify_tls: bool = True,
) -> dict[str, Any]:
    request = Request(
        runtime_health_endpoint_url(endpoint_url),
        headers={"Accept": "text/plain", "User-Agent": "Wardn/0.1 Kubernetes MCP Runtime"},
        method="GET",
    )
    try:
        context = None if verify_tls else ssl._create_unverified_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8", "replace").strip()
            return {"ready": response.status == 200, "status": response.status, "body": body}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        return {"ready": False, "status": exc.code, "body": detail or exc.reason}
    except (HTTPClientException, TimeoutError, URLError) as exc:
        raise KubernetesRuntimeNotReadyError(
            f"Kubernetes runtime gateway is not reachable: {exc}"
        ) from exc


def pod_condition_is_true(condition: Any, condition_type: str) -> bool:
    return (
        getattr(condition, "type", "") == condition_type
        and getattr(condition, "status", "") == "True"
    )


def pod_is_ready(pod: Any) -> bool:
    status = getattr(pod, "status", None)
    if status is None:
        return False
    if getattr(status, "phase", "") != "Running":
        return False
    return any(
        pod_condition_is_true(condition, "Ready")
        for condition in (getattr(status, "conditions", None) or [])
    )


def pod_failure_message(pod: Any) -> str:
    status = getattr(pod, "status", None)
    if status is None:
        return ""
    message = getattr(status, "message", "") or getattr(status, "reason", "")
    if message:
        return str(message)
    container_statuses = getattr(status, "container_statuses", None) or []
    for container_status in container_statuses:
        state = getattr(container_status, "state", None)
        waiting = getattr(state, "waiting", None)
        terminated = getattr(state, "terminated", None)
        for detail in (waiting, terminated):
            if detail is None:
                continue
            reason = getattr(detail, "reason", "")
            detail_message = getattr(detail, "message", "")
            if reason or detail_message:
                return ": ".join(item for item in (reason, detail_message) if item)
    return ""


class KubernetesRuntimeReconciler:
    def __init__(
        self,
        *,
        core_v1: Any,
        apps_v1: Any | None = None,
        networking_v1: Any | None = None,
        api_exception_class: type[Exception],
        settings=None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1 or core_v1
        self.networking_v1 = networking_v1 or core_v1
        self.api_exception_class = api_exception_class
        self.settings = settings or get_settings()
        self.sleep = sleep
        self.monotonic = monotonic

    def reconcile(self, manifest: KubernetesRuntimeManifest) -> KubernetesReconcileResult:
        self.create_namespace(manifest)
        self.create_or_replace_secret(manifest)
        self.create_or_replace_deployment(manifest)
        self.create_or_replace_service(manifest)
        self.create_or_replace_ingress(manifest)
        endpoint_url = (
            runtime_ingress_endpoint_url(names=manifest.names, settings=self.settings)
            if manifest.ingress is not None
            else runtime_service_endpoint_url(
                names=manifest.names,
                gateway_port=self.settings.mcp_runtime_kubernetes_service_port,
            )
        )
        return KubernetesReconcileResult(
            endpoint_url=endpoint_url,
        )

    def create_namespace(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self._call_api(self.core_v1.create_namespace, body=manifest.namespace)
        except self.api_exception_class as exc:
            if self._is_status(exc, 409):
                return
            raise KubernetesReconcileError(
                f"Kubernetes namespace reconcile failed: {self._api_error_detail(exc)}"
            ) from exc

    def create_or_replace_secret(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self._call_api(
                self.core_v1.create_namespaced_secret,
                namespace=manifest.names.namespace,
                body=manifest.secret,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes secret reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self._call_api(
                    self.core_v1.replace_namespaced_secret,
                    name=manifest.names.secret_name,
                    namespace=manifest.names.namespace,
                    body=manifest.secret,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    f"Kubernetes secret replace failed: {self._api_error_detail(replace_exc)}"
                ) from replace_exc

    def create_or_replace_deployment(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self._call_api(
                self.apps_v1.create_namespaced_deployment,
                namespace=manifest.names.namespace,
                body=manifest.deployment,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes deployment reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self._call_api(
                    self.apps_v1.replace_namespaced_deployment,
                    name=manifest.names.pod_name,
                    namespace=manifest.names.namespace,
                    body=manifest.deployment,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    "Kubernetes deployment replace failed: "
                    f"{self._api_error_detail(replace_exc)}"
                ) from replace_exc

    def create_or_replace_service(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self._call_api(
                self.core_v1.create_namespaced_service,
                namespace=manifest.names.namespace,
                body=manifest.service,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes service reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self._call_api(
                    self.core_v1.replace_namespaced_service,
                    name=manifest.names.service_name,
                    namespace=manifest.names.namespace,
                    body=manifest.service,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    f"Kubernetes service replace failed: {self._api_error_detail(replace_exc)}"
                ) from replace_exc

    def create_or_replace_ingress(self, manifest: KubernetesRuntimeManifest) -> None:
        if manifest.ingress is None:
            return
        try:
            self._call_api(
                self.networking_v1.create_namespaced_ingress,
                namespace=manifest.names.namespace,
                body=manifest.ingress,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes ingress reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self._call_api(
                    self.networking_v1.replace_namespaced_ingress,
                    name=manifest.names.ingress_name,
                    namespace=manifest.names.namespace,
                    body=manifest.ingress,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    f"Kubernetes ingress replace failed: {self._api_error_detail(replace_exc)}"
                ) from replace_exc

    def delete_runtime_objects(
        self,
        names: KubernetesRuntimeNames,
        *,
        delete_resources: bool = False,
    ) -> None:
        if not delete_resources:
            self.scale_deployment(names, replicas=0)
            return
        self.delete_ingress(names)
        self.delete_service(names)
        self.delete_deployment(names)
        self.delete_secret(names)

    def delete_ingress(self, names: KubernetesRuntimeNames) -> None:
        try:
            self._call_api(
                self.networking_v1.delete_namespaced_ingress,
                name=names.ingress_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 404):
                raise KubernetesReconcileError(
                    f"Kubernetes ingress delete failed: {self._api_error_detail(exc)}"
                ) from exc

    def delete_service(self, names: KubernetesRuntimeNames) -> None:
        try:
            self._call_api(
                self.core_v1.delete_namespaced_service,
                name=names.service_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 404):
                raise KubernetesReconcileError(
                    f"Kubernetes service delete failed: {self._api_error_detail(exc)}"
                ) from exc

    def scale_deployment(self, names: KubernetesRuntimeNames, *, replicas: int) -> None:
        try:
            self._call_api(
                self.apps_v1.patch_namespaced_deployment_scale,
                name=names.pod_name,
                namespace=names.namespace,
                body={"spec": {"replicas": replicas}},
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 404):
                raise KubernetesReconcileError(
                    f"Kubernetes deployment scale failed: {self._api_error_detail(exc)}"
                ) from exc

    def delete_deployment(self, names: KubernetesRuntimeNames) -> None:
        try:
            self._call_api(
                self.apps_v1.delete_namespaced_deployment,
                name=names.pod_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 404):
                raise KubernetesReconcileError(
                    f"Kubernetes deployment delete failed: {self._api_error_detail(exc)}"
                ) from exc

    def delete_secret(self, names: KubernetesRuntimeNames) -> None:
        try:
            self._call_api(
                self.core_v1.delete_namespaced_secret,
                name=names.secret_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 404):
                raise KubernetesReconcileError(
                    f"Kubernetes secret delete failed: {self._api_error_detail(exc)}"
                ) from exc

    def read_deployment(self, names: KubernetesRuntimeNames) -> Any:
        try:
            return self._call_api(
                self.apps_v1.read_namespaced_deployment,
                name=names.pod_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            raise KubernetesReconcileError(
                f"Kubernetes deployment read failed: {self._api_error_detail(exc)}"
            ) from exc

    def wait_for_deployment_ready(
        self,
        names: KubernetesRuntimeNames,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 1,
    ) -> Any:
        deadline = self.monotonic() + (
            timeout_seconds or self.settings.mcp_runtime_kubernetes_startup_timeout_seconds
        )
        last_ready = 0
        last_desired = 0
        while self.monotonic() < deadline:
            deployment = self.read_deployment(names)
            spec = getattr(deployment, "spec", None)
            status = getattr(deployment, "status", None)
            last_desired = int(getattr(spec, "replicas", 1) or 1)
            last_ready = int(
                getattr(status, "ready_replicas", 0)
                or getattr(status, "available_replicas", 0)
                or 0
            )
            if last_ready >= last_desired:
                return deployment
            self.sleep(poll_interval_seconds)
        raise KubernetesRuntimeNotReadyError(
            "Kubernetes runtime deployment did not become ready; "
            f"ready={last_ready}, desired={last_desired or 1}"
        )

    def wait_for_gateway_ready(
        self,
        endpoint_url: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 1,
    ) -> dict[str, Any]:
        deadline = self.monotonic() + (
            timeout_seconds or self.settings.mcp_runtime_kubernetes_startup_timeout_seconds
        )
        last_error = ""
        while self.monotonic() < deadline:
            try:
                status_payload = get_gateway_health(
                    endpoint_url,
                    verify_tls=self.settings.mcp_runtime_kubernetes_ingress_tls_verify,
                )
                if status_payload.get("ready") is True:
                    return status_payload
                last_error = str(status_payload)
            except KubernetesRuntimeNotReadyError as exc:
                last_error = str(exc)
            self.sleep(poll_interval_seconds)
        raise KubernetesRuntimeNotReadyError(
            f"Kubernetes runtime gateway did not become ready: {last_error}"
        )

    def wait_until_ready(
        self,
        manifest: KubernetesRuntimeManifest,
        *,
        endpoint_url: str,
    ) -> KubernetesReconcileResult:
        deployment = self.wait_for_deployment_ready(manifest.names)
        if manifest.health_path is None:
            return KubernetesReconcileResult(
                endpoint_url=endpoint_url,
                pod=deployment,
                gateway_status={"ready": True, "source": "deployment"},
            )
        gateway_status = self.wait_for_gateway_ready(endpoint_url)
        return KubernetesReconcileResult(
            endpoint_url=endpoint_url,
            pod=deployment,
            gateway_status=gateway_status,
        )

    def _is_status(self, exc: Exception, status_code: int) -> bool:
        return int(getattr(exc, "status", 0) or 0) == status_code

    def _api_error_detail(self, exc: Exception) -> str:
        status = getattr(exc, "status", None)
        reason = getattr(exc, "reason", "")
        body = getattr(exc, "body", "")
        parts = [str(item) for item in (status, reason, body) if item]
        return " ".join(parts) or str(exc)

    def _api_request_timeout(self) -> tuple[float, float]:
        read_timeout = float(
            getattr(
                self.settings,
                "mcp_runtime_kubernetes_api_timeout_seconds",
                KUBERNETES_API_READ_TIMEOUT_SECONDS,
            )
            or KUBERNETES_API_READ_TIMEOUT_SECONDS
        )
        read_timeout = max(1.0, read_timeout)
        connect_timeout = min(KUBERNETES_API_CONNECT_TIMEOUT_SECONDS, read_timeout)
        return (connect_timeout, read_timeout)

    def _call_api(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs, _request_timeout=self._api_request_timeout())
        except TypeError as exc:
            if "_request_timeout" not in str(exc):
                raise
            return method(*args, **kwargs)


class KubernetesRuntimeProvider:
    name = RUNTIME_PROVIDER_KUBERNETES

    def __init__(
        self,
        client_factory: KubernetesClientFactory | None = None,
        reconciler_factory: Callable[..., KubernetesRuntimeReconciler] | None = None,
    ) -> None:
        self._client_factory = client_factory or KubernetesClientFactory()
        self._reconciler_factory = reconciler_factory or KubernetesRuntimeReconciler

    def supports(self, installation: MCPServerInstallation) -> bool:
        return runtime_kind(installation) == RUNTIME_KIND_PACKAGE

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        runtime_config = installation.runtime_config or {}
        settings = get_settings()
        if is_oci_runtime(runtime_config):
            command = oci_runtime_image(runtime_config)
            args = oci_runtime_container_args(
                runtime_config,
                port=settings.mcp_runtime_kubernetes_service_port,
            )
            cwd = ""
            runtime_image = command
            workload_runtime = "oci-image"
        else:
            runtime = package_runtime(installation)
            command, args, cwd = kubernetes_runtime_process(runtime, runtime_config)
            runtime_image = supergateway_image(installation, settings=settings)
            workload_runtime = "supergateway"
        provider_config = {
            "installationRuntimeConfig": runtime_config,
            "workloadKind": "deployment",
            "workloadRuntime": workload_runtime,
            "objectIdentity": "runtime_config_fingerprint",
            "runtimeImage": runtime_image,
            "gatewayBaseImage": settings.mcp_runtime_kubernetes_gateway_image,
            "gatewayUvxImage": settings.mcp_runtime_kubernetes_gateway_uvx_image,
            "gatewayDenoImage": settings.mcp_runtime_kubernetes_gateway_deno_image,
            "servicePort": settings.mcp_runtime_kubernetes_service_port,
            "namespacePrefix": settings.mcp_runtime_kubernetes_namespace_prefix,
            "namespaceLabels": settings.mcp_runtime_kubernetes_namespace_labels_json,
            "namespaceAnnotations": settings.mcp_runtime_kubernetes_namespace_annotations_json,
            "imagePullSecretName": settings.mcp_runtime_kubernetes_image_pull_secret_name,
            "ingressEnabled": settings.mcp_runtime_kubernetes_ingress_enabled,
            "ingressBaseDomain": settings.mcp_runtime_kubernetes_ingress_base_domain,
            "ingressClassName": settings.mcp_runtime_kubernetes_ingress_class_name,
            "ingressScheme": settings.mcp_runtime_kubernetes_ingress_scheme,
            "ingressTlsVerify": settings.mcp_runtime_kubernetes_ingress_tls_verify,
            "ingressTlsSecretName": settings.mcp_runtime_kubernetes_ingress_tls_secret_name,
            "ingressTraefikEntrypoints": (
                settings.mcp_runtime_kubernetes_ingress_traefik_entrypoints
            ),
            "ingressExternalDnsEnabled": (
                settings.mcp_runtime_kubernetes_ingress_external_dns_enabled
            ),
            "ingressAnnotations": settings.mcp_runtime_kubernetes_ingress_annotations_json,
            "cpuRequest": settings.mcp_runtime_kubernetes_cpu_request,
            "cpuLimit": settings.mcp_runtime_kubernetes_cpu_limit,
            "memoryRequest": settings.mcp_runtime_kubernetes_memory_request,
            "memoryLimit": settings.mcp_runtime_kubernetes_memory_limit,
            "startupTimeoutSeconds": settings.mcp_runtime_kubernetes_startup_timeout_seconds,
        }
        return RuntimeSpec(
            installation_id=str(getattr(installation, "id", "")),
            server_name=installation.server_name,
            server_version=installation.installed_version,
            provider_name=self.name,
            runtime_kind=runtime_kind(installation),
            transport=RUNTIME_TRANSPORT_STREAMABLE_HTTP,
            runtime_config_fingerprint=fingerprint_payload(provider_config),
            secret_config_fingerprint=secret_fingerprint_payload(
                installation.secret_references or {}
            ),
            command=command,
            args=tuple(args),
            cwd=cwd,
            workspace_id=str(installation.workspace_id or ""),
        )

    def list_tools(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> list[dict[str, Any]]:
        if runtime_session is None:
            raise NotImplementedError(
                "kubernetes MCP runtime tool discovery requires a runtime session; "
                "use a tracked runtime call path before invocation"
            )
        manifest = build_runtime_manifests(installation, runtime_session)
        reconciler = self._new_reconciler()
        reconcile_result = reconciler.reconcile(manifest)
        runtime_session.namespace = manifest.names.namespace
        runtime_session.pod_name = manifest.names.pod_name
        runtime_session.endpoint_url = reconcile_result.endpoint_url
        reconciler.wait_until_ready(
            manifest,
            endpoint_url=runtime_session.endpoint_url,
        )
        return mcp_client.list_tools(
            runtime_session.endpoint_url,
            runtime_request_headers(installation),
            verify_tls=get_settings().mcp_runtime_kubernetes_ingress_tls_verify,
        )

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        request_meta: dict[str, Any] | None = None,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        if runtime_session is None:
            raise NotImplementedError(
                "kubernetes MCP runtime reconciliation requires a runtime session"
            )
        manifest = build_runtime_manifests(installation, runtime_session)
        reconciler = self._new_reconciler()
        reconcile_result = reconciler.reconcile(manifest)
        runtime_session.namespace = manifest.names.namespace
        runtime_session.pod_name = manifest.names.pod_name
        runtime_session.endpoint_url = reconcile_result.endpoint_url
        reconciler.wait_until_ready(
            manifest,
            endpoint_url=runtime_session.endpoint_url,
        )
        return mcp_client.call_tool(
            runtime_session.endpoint_url,
            runtime_request_headers(installation),
            tool_name=tool_name,
            arguments=arguments,
            request_meta=request_meta,
            verify_tls=get_settings().mcp_runtime_kubernetes_ingress_tls_verify,
        )

    def ensure_runtime(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
        wait_ready: bool = True,
    ) -> RuntimeHealth:
        if runtime_session is None:
            raise NotImplementedError(
                "kubernetes MCP runtime reconciliation requires a runtime session"
            )
        manifest = build_runtime_manifests(installation, runtime_session)
        reconciler = self._new_reconciler()
        reconcile_result = reconciler.reconcile(manifest)
        runtime_session.namespace = manifest.names.namespace
        runtime_session.pod_name = manifest.names.pod_name
        runtime_session.endpoint_url = reconcile_result.endpoint_url
        if not wait_ready:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_NOT_READY,
                healthy=True,
                ready=False,
                message="Kubernetes runtime was reconciled; readiness was not waited.",
                details={"endpointUrl": runtime_session.endpoint_url},
            )
        ready_result = reconciler.wait_until_ready(
            manifest,
            endpoint_url=runtime_session.endpoint_url,
        )
        return RuntimeHealth(
            status=RUNTIME_HEALTH_READY,
            healthy=True,
            ready=True,
            message="Kubernetes runtime is ready.",
            details=ready_result.gateway_status,
        )

    def stop_runtime(
        self,
        runtime_session: MCPRuntimeSession,
        *,
        delete_resources: bool = False,
    ) -> None:
        names = runtime_object_names_for_session(runtime_session, prefer_stored_names=True)
        self._new_reconciler().delete_runtime_objects(
            names,
            delete_resources=delete_resources,
        )

    def health(self, runtime_session: MCPRuntimeSession) -> RuntimeHealth:
        if runtime_session.status in {"stopped", "failed", "expired"}:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_STOPPED,
                healthy=False,
                ready=False,
                message=f"Runtime session is {runtime_session.status}.",
            )
        return RuntimeHealth(
            status=RUNTIME_HEALTH_NOT_READY,
            healthy=False,
            ready=False,
            message="Kubernetes runtime health polling is not wired into this endpoint yet.",
        )

    def _new_reconciler(self) -> KubernetesRuntimeReconciler:
        client_set = self._client_factory.load()
        return self._reconciler_factory(
            core_v1=client_set.core_v1,
            apps_v1=client_set.apps_v1,
            networking_v1=client_set.networking_v1,
            api_exception_class=self._client_factory.api_exception_class(),
        )
