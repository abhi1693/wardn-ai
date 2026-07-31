import re
from dataclasses import dataclass, field
from typing import Any

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
KUBERNETES_RUNTIME_TMP_VOLUME_NAME = "runtime-tmp"
KUBERNETES_RUNTIME_TMP_MOUNT_PATH = "/tmp"
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
    custom_objects: Any | None = None


@dataclass(frozen=True)
class KubernetesNetworkDiscovery:
    dns_namespace: str = "kube-system"
    dns_selector: dict[str, str] = field(default_factory=lambda: {"k8s-app": "kube-dns"})
    dns_service_cidrs: tuple[str, ...] = ()
    dns_ports: tuple[int, ...] = (53,)
    service_cidrs: tuple[str, ...] = ()
    pod_cidrs: tuple[str, ...] = ()
    kubernetes_api_host: str = ""
    kubernetes_api_cidrs: tuple[str, ...] = ()
    kubernetes_api_service_ports: tuple[int, ...] = (443,)
    kubernetes_api_endpoint_ports: tuple[int, ...] = (443, 6443)
    cni_provider: str = "network_policy"
    supports_cilium: bool = False
    supports_calico: bool = False


@dataclass(frozen=True)
class KubernetesRuntimeNames:
    namespace: str
    pod_name: str
    service_name: str
    secret_name: str
    ingress_name: str


@dataclass(frozen=True)
class KubernetesCustomNetworkPolicyRef:
    group: str
    version: str
    plural: str
    kind: str
    name: str


@dataclass(frozen=True)
class KubernetesCustomNetworkPolicy:
    ref: KubernetesCustomNetworkPolicyRef
    body: dict[str, Any]


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
    network_policies: list[Any]
    custom_network_policies: list[KubernetesCustomNetworkPolicy] = field(default_factory=list)
    network_policy_cleanup_names: list[str] = field(default_factory=list)
    custom_network_policy_cleanup_refs: list[KubernetesCustomNetworkPolicyRef] = field(
        default_factory=list
    )
    ingress: Any | None = None
    health_path: str | None = KUBERNETES_SUPERGATEWAY_HEALTH_PATH


@dataclass(frozen=True)
class KubernetesReconcileResult:
    endpoint_url: str
    pod: Any | None = None
    gateway_status: dict[str, Any] | None = None
