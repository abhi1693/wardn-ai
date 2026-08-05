import json
import logging
import os
import re
import shlex
import socket
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_registry.python_runtime import (
    python_runtime_dependency_values,
    resolve_python_runtime_requirement,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_TRANSPORT_STREAMABLE_HTTP,
    fingerprint_payload,
    package_runtime,
    package_transport_type,
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
    KubernetesCustomNetworkPolicy,
    KubernetesCustomNetworkPolicyRef,
    KubernetesMetadataError,
    KubernetesNetworkDiscovery,
    KubernetesReconcileError,
    KubernetesRuntimeManifest,
    KubernetesRuntimeNames,
)

logger = logging.getLogger(__name__)
NETWORK_POLICY_DOMAIN_LABEL_PATTERN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

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
RUNTIME_PRIVATE_EGRESS_CIDRS = [
    "10.0.0.0/8",
    "100.64.0.0/10",
    "172.16.0.0/12",
    "192.168.0.0/16",
]
RUNTIME_NETWORK_POLICY_CONFIG_KEY = "networkPolicy"
RUNTIME_NETWORK_POLICY_CUSTOM_EGRESS_LIMIT = 20
RUNTIME_NETWORK_POLICY_REMOTE_DESTINATION_LIMIT = 20
KUBERNETES_NETWORK_POLICY_BACKEND_AUTO = "auto"
KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD = "network_policy"
KUBERNETES_NETWORK_POLICY_BACKEND_CILIUM = "cilium"
KUBERNETES_NETWORK_POLICY_BACKEND_CALICO = "calico"
KUBERNETES_STRUCTURED_CONTENT_PROXY_PATH = (
    "/opt/wardn-runtime/structured-content-proxy.mjs"
)
PACKAGE_REGISTRY_REMOTE_DESTINATIONS: dict[str, tuple[dict[str, str | int], ...]] = {
    "npm": (
        {
            "label": "npm-registry",
            "host": "registry.npmjs.org",
            "port": 443,
        },
    ),
    "pypi": (
        {
            "label": "pypi-index",
            "host": "pypi.org",
            "port": 443,
        },
        {
            "label": "pypi-files",
            "host": "files.pythonhosted.org",
            "port": 443,
        },
    ),
    "uvx": (
        {
            "label": "pypi-index",
            "host": "pypi.org",
            "port": 443,
        },
        {
            "label": "pypi-files",
            "host": "files.pythonhosted.org",
            "port": 443,
        },
    ),
}
KUBERNETES_API_SERVICE_NAMESPACE = "default"
KUBERNETES_API_SERVICE_NAME = "kubernetes"
KUBERNETES_API_DEFAULT_SERVICE_PORT = 443
KUBERNETES_API_COMMON_ENDPOINT_PORT = 6443
KUBERNETES_API_DISCOVERY_SERVICE_NAME = "kubernetes"
KUBERNETES_API_DISCOVERY_SERVICE_NAMESPACE = "default"
KUBERNETES_SERVICE_CIDR_GROUP = "networking.k8s.io"
KUBERNETES_SERVICE_CIDR_VERSION = "v1"
KUBERNETES_SERVICE_CIDR_PLURAL = "servicecidrs"
KUBE_DNS_SERVICE_NAMES = ("kube-dns", "coredns")
CILIUM_NETWORK_POLICY_GROUP = "cilium.io"
CILIUM_NETWORK_POLICY_VERSION = "v2"
CILIUM_NETWORK_POLICY_PLURAL = "ciliumnetworkpolicies"
CILIUM_NETWORK_POLICY_KIND = "CiliumNetworkPolicy"
CALICO_NETWORK_POLICY_GROUP = "projectcalico.org"
CALICO_NETWORK_POLICY_VERSION = "v3"
CALICO_NETWORK_POLICY_PLURAL = "networkpolicies"
CALICO_NETWORK_POLICY_KIND = "NetworkPolicy"
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


def runtime_network_policy_has_intents(raw_config: dict[str, Any]) -> bool:
    mode = str(raw_config.get("mode") or "").strip().casefold()
    if mode == "intent":
        return True
    if mode == "legacy":
        return False
    if not raw_config:
        return True
    return any(
        key in raw_config
        for key in (
            "allowKubernetesApi",
            "allowRemoteMcpEgress",
            "allowRuntimeDependencyEgress",
            "denyOtherEgress",
        )
    )


def bool_config(
    raw_config: dict[str, Any],
    key: str,
    *,
    fallback: bool,
) -> bool:
    value = raw_config.get(key)
    if isinstance(value, bool):
        return value
    return fallback


def runtime_config_registry_type(
    installation: MCPServerInstallation,
    runtime_config: dict[str, Any],
) -> str:
    package = runtime_config.get("package")
    sources = [runtime_config]
    if isinstance(package, dict):
        sources.append(package)
    for source in sources:
        package_registry_type = str(source.get("registryType") or "").strip().lower()
        if package_registry_type:
            return package_registry_type
    if isinstance(package, dict) and str(package.get("identifier") or "").strip():
        return str(installation.install_type or "").strip().lower()
    return ""


def package_registry_remote_destinations(
    installation: MCPServerInstallation,
    runtime_config: dict[str, Any],
) -> list[dict[str, str | int]]:
    package_registry_type = runtime_config_registry_type(installation, runtime_config)
    destinations = PACKAGE_REGISTRY_REMOTE_DESTINATIONS.get(package_registry_type, ())
    return [dict(destination) for destination in destinations]


def remote_destination_from_url(value: Any, *, label: str = "") -> dict[str, str | int] | None:
    raw_url = str(value or "").strip()
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return {
        "label": label or parsed.hostname,
        "host": parsed.hostname,
        "port": parsed.port or (80 if parsed.scheme == "http" else 443),
    }


def package_transport_remote_destinations(
    runtime_config: dict[str, Any],
) -> list[dict[str, str | int]]:
    package = runtime_config.get("package")
    raw_transports = [runtime_config.get("transport")]
    if isinstance(package, dict):
        raw_transports.append(package.get("transport"))

    destinations: list[dict[str, str | int]] = []
    for transport in raw_transports:
        if not isinstance(transport, dict):
            continue
        if destination := remote_destination_from_url(transport.get("url")):
            destinations.append(destination)
        env = transport.get("env")
        if isinstance(env, dict):
            for name, value in env.items():
                destination = remote_destination_from_url(value, label=str(name))
                if destination is not None:
                    destinations.append(destination)
    return destinations


def package_transport_env_values(runtime_config: dict[str, Any]) -> dict[str, str]:
    package = runtime_config.get("package")
    raw_transports = [runtime_config.get("transport")]
    if isinstance(package, dict):
        raw_transports.append(package.get("transport"))

    env_values: dict[str, str] = {}
    for transport in raw_transports:
        if not isinstance(transport, dict):
            continue
        env = transport.get("env")
        if not isinstance(env, dict):
            continue
        for name, value in env.items():
            key = str(name or "").strip()
            env_value = str(value or "").strip()
            if key and env_value:
                env_values[key] = env_value
    return env_values


def merge_remote_destinations(
    *destination_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for destinations in destination_groups:
        for destination in destinations:
            key = (str(destination.get("host") or ""), int(destination.get("port") or 443))
            if key in seen:
                continue
            seen.add(key)
            merged.append(destination)
    return merged


def network_policy_config(
    installation: MCPServerInstallation,
    *,
    settings=None,
) -> dict[str, Any]:
    runtime_settings = settings or get_settings()
    runtime_config = installation.runtime_config or {}
    raw_config = runtime_config.get(RUNTIME_NETWORK_POLICY_CONFIG_KEY)
    if not isinstance(raw_config, dict):
        raw_config = {}

    uses_intents = runtime_network_policy_has_intents(raw_config)
    deny_other_egress = bool_config(
        raw_config,
        "denyOtherEgress",
        fallback=bool_config(raw_config, "isolationEnabled", fallback=True),
    )
    allow_kubernetes_api = bool_config(
        raw_config,
        "allowKubernetesApi",
        fallback=bool_config(raw_config, "inClusterKubernetesApi", fallback=False),
    )
    allow_remote_mcp_egress = bool_config(
        raw_config,
        "allowRemoteMcpEgress",
        fallback=True if uses_intents else False,
    )
    allow_runtime_dependency_egress = bool_config(
        raw_config,
        "allowRuntimeDependencyEgress",
        fallback=allow_remote_mcp_egress,
    )
    if uses_intents:
        public_egress = False
        private_egress = False
        private_egress_ports = [80, 443]
        custom_egress = normalize_custom_egress_rules(raw_config.get("customEgress"))
        isolation_enabled = deny_other_egress
    else:
        public_egress = (
            bool(raw_config.get("publicEgress", False))
            and runtime_settings.mcp_runtime_kubernetes_allow_public_egress
        )
        private_egress = bool(raw_config.get("privateEgress", False))
        private_egress_ports = normalize_network_policy_ports(
            raw_config.get("privateEgressPorts"),
            default=[80, 443],
            field_name="Kubernetes runtime private egress ports",
        )
        custom_egress = normalize_custom_egress_rules(raw_config.get("customEgress"))
        isolation_enabled = bool(raw_config.get("isolationEnabled", True))

    remote_destinations = []
    if allow_remote_mcp_egress or allow_runtime_dependency_egress:
        remote_destinations = merge_remote_destinations(
            *(
                [
                    normalize_remote_mcp_destinations(raw_config.get("remoteDestinations")),
                    normalize_remote_mcp_destinations(
                        package_transport_remote_destinations(runtime_config)
                    ),
                ]
                if allow_remote_mcp_egress
                else []
            ),
            *(
                [
                    normalize_remote_mcp_destinations(
                        package_registry_remote_destinations(installation, runtime_config)
                    )
                ]
                if allow_runtime_dependency_egress
                else []
            ),
        )

    return {
        "isolationEnabled": isolation_enabled,
        "denyOtherEgress": deny_other_egress,
        "allowKubernetesApi": allow_kubernetes_api,
        "allowRemoteMcpEgress": allow_remote_mcp_egress,
        "allowRuntimeDependencyEgress": allow_runtime_dependency_egress,
        "publicEgress": public_egress,
        "privateEgress": private_egress,
        "privateEgressPorts": private_egress_ports,
        "inClusterKubernetesApi": allow_kubernetes_api,
        "customEgress": custom_egress,
        "remoteDestinations": remote_destinations,
    }


def has_explicit_network_policy_config(installation: MCPServerInstallation) -> bool:
    runtime_config = installation.runtime_config or {}
    return isinstance(runtime_config.get(RUNTIME_NETWORK_POLICY_CONFIG_KEY), dict)


def normalize_network_policy_ports(
    raw_ports: Any,
    *,
    default: list[int],
    field_name: str,
) -> list[int]:
    if raw_ports is None:
        return list(default)
    if not isinstance(raw_ports, list) or not raw_ports:
        raise KubernetesMetadataError(f"{field_name} must be a non-empty list")
    ports: list[int] = []
    for raw_port in raw_ports:
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise KubernetesMetadataError(f"{field_name} are invalid") from exc
        if port < 1 or port > 65_535:
            raise KubernetesMetadataError(f"{field_name} must be between 1 and 65535")
        if port not in ports:
            ports.append(port)
    return ports


def normalize_network_policy_domain(value: Any) -> str:
    domain = str(value or "").strip().rstrip(".").lower()
    if not domain:
        return ""
    if ip_cidr_for_address(domain) is not None:
        raise KubernetesMetadataError("Kubernetes runtime custom egress domain must be a hostname")
    if len(domain) > 253:
        raise KubernetesMetadataError(
            "Kubernetes runtime custom egress domain is too long"
        )
    labels = domain.split(".")
    if any(not NETWORK_POLICY_DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise KubernetesMetadataError("Kubernetes runtime custom egress domain is invalid")
    return domain


def normalize_custom_egress_rules(raw_rules: Any) -> list[dict[str, Any]]:
    if raw_rules is None:
        return []
    if not isinstance(raw_rules, list):
        raise KubernetesMetadataError("Kubernetes runtime custom egress rules must be a list")
    if len(raw_rules) > RUNTIME_NETWORK_POLICY_CUSTOM_EGRESS_LIMIT:
        raise KubernetesMetadataError("Kubernetes runtime custom egress rules exceed the limit")

    rules: list[dict[str, Any]] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise KubernetesMetadataError("Kubernetes runtime custom egress rule is invalid")
        ports = normalize_network_policy_ports(
            raw_rule.get("ports"),
            default=[443],
            field_name="Kubernetes runtime custom egress ports",
        )
        label = str(raw_rule.get("label") or "").strip()[:120]
        destination_type = str(
            raw_rule.get("destinationType") or raw_rule.get("destination_type") or ""
        ).strip().casefold()
        if not destination_type:
            destination_type = "domain" if str(raw_rule.get("domain") or "").strip() else "cidr"
        if destination_type not in {"cidr", "domain"}:
            raise KubernetesMetadataError(
                "Kubernetes runtime custom egress destination type is invalid"
            )

        if destination_type == "domain":
            domain = normalize_network_policy_domain(raw_rule.get("domain"))
            if not domain:
                raise KubernetesMetadataError(
                    "Kubernetes runtime custom egress domain is required"
                )
            rules.append(
                {
                    "label": label,
                    "destinationType": "domain",
                    "domain": domain,
                    "ports": ports,
                }
            )
            continue

        raw_cidr = str(raw_rule.get("cidr") or "").strip()
        if not raw_cidr:
            raise KubernetesMetadataError("Kubernetes runtime custom egress cidr is required")
        try:
            cidr = str(ip_network(raw_cidr, strict=False))
        except ValueError as exc:
            raise KubernetesMetadataError(
                "Kubernetes runtime custom egress cidr is invalid"
            ) from exc
        rules.append(
            {
                "label": label,
                "destinationType": "cidr",
                "cidr": cidr,
                "ports": ports,
            }
        )
    return rules


def ip_cidr_for_address(value: str) -> str | None:
    try:
        address = ip_address(value.strip())
    except ValueError:
        return None
    prefix_length = 32 if address.version == 4 else 128
    return f"{address}/{prefix_length}"


def normalize_ip_cidr(value: str) -> str | None:
    raw_value = value.strip()
    if not raw_value:
        return None
    try:
        return str(ip_network(raw_value, strict=False))
    except ValueError:
        return ip_cidr_for_address(raw_value)


def resolve_remote_host_cidrs(host: str) -> list[str]:
    if cidr := ip_cidr_for_address(host):
        return [cidr]
    cidrs: list[str] = []
    try:
        address_infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    for address_info in address_infos:
        sockaddr = address_info[4]
        if not sockaddr:
            continue
        cidr = ip_cidr_for_address(str(sockaddr[0]))
        if cidr and cidr not in cidrs:
            cidrs.append(cidr)
    return cidrs


def normalize_remote_mcp_destinations(raw_destinations: Any) -> list[dict[str, Any]]:
    if raw_destinations is None:
        return []
    if not isinstance(raw_destinations, list):
        raise KubernetesMetadataError("Kubernetes runtime remote MCP destinations must be a list")
    if len(raw_destinations) > RUNTIME_NETWORK_POLICY_REMOTE_DESTINATION_LIMIT:
        raise KubernetesMetadataError("Kubernetes runtime remote MCP destinations exceed the limit")

    destinations: list[dict[str, Any]] = []
    for raw_destination in raw_destinations:
        if not isinstance(raw_destination, dict):
            raise KubernetesMetadataError("Kubernetes runtime remote MCP destination is invalid")
        host = str(raw_destination.get("host") or "").strip().rstrip(".").lower()
        if not host:
            continue
        try:
            port = int(raw_destination.get("port") or 443)
        except (TypeError, ValueError) as exc:
            raise KubernetesMetadataError(
                "Kubernetes runtime remote MCP destination port is invalid"
            ) from exc
        if port < 1 or port > 65_535:
            raise KubernetesMetadataError(
                "Kubernetes runtime remote MCP destination port must be between 1 and 65535"
            )

        cidrs = []
        raw_cidrs = raw_destination.get("cidrs")
        if isinstance(raw_cidrs, list):
            for raw_cidr in raw_cidrs:
                cidr = normalize_ip_cidr(str(raw_cidr))
                if cidr and cidr not in cidrs:
                    cidrs.append(cidr)
        if not cidrs:
            cidrs = resolve_remote_host_cidrs(host)

        destinations.append(
            {
                "label": str(raw_destination.get("label") or host).strip()[:120],
                "host": host,
                "port": port,
                "cidrs": cidrs,
            }
        )
    return destinations


def in_cluster_kubernetes_api_cidr() -> str | None:
    service_host = os.environ.get("KUBERNETES_SERVICE_HOST", "").strip()
    if not service_host:
        return None
    return ip_cidr_for_address(service_host)


def in_cluster_kubernetes_api_service_ports() -> list[int]:
    ports: list[int] = []
    for env_name in ("KUBERNETES_SERVICE_PORT_HTTPS", "KUBERNETES_SERVICE_PORT"):
        raw_port = os.environ.get(env_name, "").strip()
        if not raw_port:
            continue
        try:
            port = int(raw_port)
        except ValueError:
            continue
        if 1 <= port <= 65_535 and port not in ports:
            ports.append(port)
    if KUBERNETES_API_DEFAULT_SERVICE_PORT not in ports:
        ports.append(KUBERNETES_API_DEFAULT_SERVICE_PORT)
    return ports


def in_cluster_kubernetes_api_endpoint_ports() -> list[int]:
    ports = in_cluster_kubernetes_api_service_ports()
    if KUBERNETES_API_COMMON_ENDPOINT_PORT not in ports:
        ports.append(KUBERNETES_API_COMMON_ENDPOINT_PORT)
    return ports


def unique_tuple(values: list[str] | list[int]) -> tuple:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def valid_service_cidrs(values: list[str]) -> list[str]:
    cidrs: list[str] = []
    for value in values:
        raw_value = str(value or "").strip()
        if not raw_value or raw_value.casefold() == "none":
            continue
        cidr = normalize_ip_cidr(raw_value)
        if cidr and cidr not in cidrs:
            cidrs.append(cidr)
    return cidrs


def service_cluster_cidrs(service: Any) -> list[str]:
    spec = getattr(service, "spec", None)
    if spec is None:
        return []
    values: list[str] = []
    cluster_ips = getattr(spec, "cluster_ips", None)
    if isinstance(cluster_ips, list):
        values.extend(str(value) for value in cluster_ips)
    cluster_ip = getattr(spec, "cluster_ip", "")
    if cluster_ip:
        values.append(str(cluster_ip))
    return valid_service_cidrs(values)


def service_cluster_host(service: Any) -> str:
    spec = getattr(service, "spec", None)
    if spec is None:
        return ""
    cluster_ip = str(getattr(spec, "cluster_ip", "") or "").strip()
    if cluster_ip and cluster_ip.casefold() != "none":
        return cluster_ip
    cluster_ips = getattr(spec, "cluster_ips", None)
    if isinstance(cluster_ips, list):
        for value in cluster_ips:
            host = str(value or "").strip()
            if host and host.casefold() != "none":
                return host
    return ""


def service_ports(service: Any, *, default: list[int]) -> list[int]:
    spec = getattr(service, "spec", None)
    ports: list[int] = []
    for service_port in getattr(spec, "ports", None) or []:
        try:
            port = int(getattr(service_port, "port", 0) or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65_535 and port not in ports:
            ports.append(port)
    return ports or list(default)


def service_selector_from_service(service: Any) -> dict[str, str]:
    spec = getattr(service, "spec", None)
    selector = getattr(spec, "selector", None)
    if not isinstance(selector, dict):
        return {}
    return {str(key): str(value) for key, value in selector.items() if key and value}


def kubernetes_items(response: Any) -> list[Any]:
    if isinstance(response, dict):
        items = response.get("items")
        return items if isinstance(items, list) else []
    items = getattr(response, "items", None)
    return items if isinstance(items, list) else []


def kubernetes_spec_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        spec = item.get("spec")
        return spec.get(key) if isinstance(spec, dict) else None
    spec = getattr(item, "spec", None)
    return getattr(spec, key, None)


def call_kubernetes_discovery(method: Any, *args: Any, **kwargs: Any) -> Any | None:
    if method is None:
        return None
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        logger.debug(
            "Kubernetes runtime network discovery call failed.",
            extra={
                "kubernetes_discovery_method": getattr(method, "__name__", ""),
                "error_type": exc.__class__.__name__,
            },
        )
        return None


def list_kube_system_pods(core_v1: Any, *, label_selector: str) -> list[Any]:
    response = call_kubernetes_discovery(
        getattr(core_v1, "list_namespaced_pod", None),
        namespace=KUBE_SYSTEM_NAMESPACE_NAME,
        label_selector=label_selector,
    )
    return kubernetes_items(response)


def configured_network_policy_backend(settings=None) -> str:
    runtime_settings = settings or get_settings()
    return str(
        getattr(
            runtime_settings,
            "mcp_runtime_kubernetes_network_policy_backend",
            KUBERNETES_NETWORK_POLICY_BACKEND_AUTO,
        )
        or KUBERNETES_NETWORK_POLICY_BACKEND_AUTO
    ).strip().lower()


def cni_provider_from_network_policy_backend(
    backend: str,
) -> tuple[str, bool, bool] | None:
    if backend == KUBERNETES_NETWORK_POLICY_BACKEND_CILIUM:
        return KUBERNETES_NETWORK_POLICY_BACKEND_CILIUM, True, False
    if backend == KUBERNETES_NETWORK_POLICY_BACKEND_CALICO:
        return KUBERNETES_NETWORK_POLICY_BACKEND_CALICO, False, True
    if backend == KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD:
        return KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD, False, False
    return None


def apply_network_policy_backend_override(
    cni_provider: str,
    supports_cilium: bool,
    supports_calico: bool,
    *,
    settings=None,
) -> tuple[str, bool, bool]:
    configured_backend = configured_network_policy_backend(settings)
    override = cni_provider_from_network_policy_backend(configured_backend)
    if override is not None:
        return override
    return cni_provider, supports_cilium, supports_calico


def discover_kubernetes_cni_provider(client_set: Any) -> tuple[str, bool, bool]:
    core_v1 = getattr(client_set, "core_v1", None)
    cilium_pods = [
        *list_kube_system_pods(core_v1, label_selector="k8s-app=cilium"),
        *list_kube_system_pods(core_v1, label_selector="app.kubernetes.io/name=cilium-agent"),
    ]
    if cilium_pods:
        return KUBERNETES_NETWORK_POLICY_BACKEND_CILIUM, True, False

    calico_pods = [
        *list_kube_system_pods(core_v1, label_selector="k8s-app=calico-node"),
        *list_kube_system_pods(core_v1, label_selector="app=calico-node"),
    ]
    if calico_pods:
        return KUBERNETES_NETWORK_POLICY_BACKEND_CALICO, False, True

    return KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD, False, False


def discover_kubernetes_pod_cidrs(client_set: Any) -> tuple[str, ...]:
    core_v1 = getattr(client_set, "core_v1", None)
    response = call_kubernetes_discovery(getattr(core_v1, "list_node", None))
    cidrs: list[str] = []
    for node in kubernetes_items(response):
        spec = getattr(node, "spec", None)
        pod_cidrs = getattr(spec, "pod_cidrs", None)
        if isinstance(pod_cidrs, list):
            for raw_cidr in pod_cidrs:
                cidr = normalize_ip_cidr(str(raw_cidr))
                if cidr and cidr not in cidrs:
                    cidrs.append(cidr)
        pod_cidr = getattr(spec, "pod_cidr", "")
        if pod_cidr:
            cidr = normalize_ip_cidr(str(pod_cidr))
            if cidr and cidr not in cidrs:
                cidrs.append(cidr)
    return tuple(cidrs)


def service_cidrs_from_response(response: Any) -> list[str]:
    cidrs: list[str] = []
    for item in kubernetes_items(response):
        raw_cidrs = kubernetes_spec_value(item, "cidrs")
        if not isinstance(raw_cidrs, list):
            continue
        for raw_cidr in raw_cidrs:
            cidr = normalize_ip_cidr(str(raw_cidr))
            if cidr and cidr not in cidrs:
                cidrs.append(cidr)
    return cidrs


def discover_kubernetes_service_cidrs(
    client_set: Any,
    *,
    fallback: list[str],
) -> tuple[str, ...]:
    networking_v1 = getattr(client_set, "networking_v1", None)
    cidrs = service_cidrs_from_response(
        call_kubernetes_discovery(getattr(networking_v1, "list_service_cidr", None))
    )
    if cidrs:
        return tuple(cidrs)

    custom_objects = getattr(client_set, "custom_objects", None)
    cidrs = service_cidrs_from_response(
        call_kubernetes_discovery(
            getattr(custom_objects, "list_cluster_custom_object", None),
            group=KUBERNETES_SERVICE_CIDR_GROUP,
            version=KUBERNETES_SERVICE_CIDR_VERSION,
            plural=KUBERNETES_SERVICE_CIDR_PLURAL,
        )
    )
    if cidrs:
        return tuple(cidrs)
    return unique_tuple(fallback)


def default_kubernetes_network_discovery(*, settings=None) -> KubernetesNetworkDiscovery:
    api_host = os.environ.get("KUBERNETES_SERVICE_HOST", "").strip()
    api_cidrs = []
    if cidr := in_cluster_kubernetes_api_cidr():
        api_cidrs.append(cidr)
    service_ports = in_cluster_kubernetes_api_service_ports()
    endpoint_ports = in_cluster_kubernetes_api_endpoint_ports()
    cni_provider, supports_cilium, supports_calico = apply_network_policy_backend_override(
        KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD,
        False,
        False,
        settings=settings,
    )
    return KubernetesNetworkDiscovery(
        kubernetes_api_host=api_host,
        kubernetes_api_cidrs=tuple(api_cidrs),
        kubernetes_api_service_ports=tuple(service_ports),
        kubernetes_api_endpoint_ports=tuple(endpoint_ports),
        cni_provider=cni_provider,
        supports_cilium=supports_cilium,
        supports_calico=supports_calico,
    )


def discover_kubernetes_network(client_set: Any, *, settings=None) -> KubernetesNetworkDiscovery:
    discovery = default_kubernetes_network_discovery(settings=settings)
    core_v1 = getattr(client_set, "core_v1", None)

    api_service = call_kubernetes_discovery(
        getattr(core_v1, "read_namespaced_service", None),
        name=KUBERNETES_API_DISCOVERY_SERVICE_NAME,
        namespace=KUBERNETES_API_DISCOVERY_SERVICE_NAMESPACE,
    )
    api_host = service_cluster_host(api_service) or discovery.kubernetes_api_host
    api_cidrs = service_cluster_cidrs(api_service) or list(discovery.kubernetes_api_cidrs)
    api_service_ports = service_ports(
        api_service,
        default=list(discovery.kubernetes_api_service_ports),
    )
    api_endpoint_ports = list(api_service_ports)
    if KUBERNETES_API_COMMON_ENDPOINT_PORT not in api_endpoint_ports:
        api_endpoint_ports.append(KUBERNETES_API_COMMON_ENDPOINT_PORT)

    dns_service = None
    for service_name in KUBE_DNS_SERVICE_NAMES:
        dns_service = call_kubernetes_discovery(
            getattr(core_v1, "read_namespaced_service", None),
            name=service_name,
            namespace=KUBE_SYSTEM_NAMESPACE_NAME,
        )
        if dns_service is not None:
            break
    dns_service_cidrs = service_cluster_cidrs(dns_service)
    dns_selector = service_selector_from_service(dns_service) or discovery.dns_selector
    dns_ports = service_ports(dns_service, default=list(discovery.dns_ports))
    service_cidrs = discover_kubernetes_service_cidrs(
        client_set,
        fallback=[*api_cidrs, *dns_service_cidrs],
    )
    cni_provider, supports_cilium, supports_calico = apply_network_policy_backend_override(
        *discover_kubernetes_cni_provider(client_set),
        settings=settings,
    )

    return KubernetesNetworkDiscovery(
        dns_namespace=KUBE_SYSTEM_NAMESPACE_NAME,
        dns_selector=dns_selector,
        dns_service_cidrs=tuple(dns_service_cidrs),
        dns_ports=tuple(dns_ports),
        service_cidrs=service_cidrs,
        pod_cidrs=discover_kubernetes_pod_cidrs(client_set),
        kubernetes_api_host=api_host,
        kubernetes_api_cidrs=tuple(api_cidrs),
        kubernetes_api_service_ports=tuple(api_service_ports),
        kubernetes_api_endpoint_ports=tuple(api_endpoint_ports),
        cni_provider=cni_provider,
        supports_cilium=supports_cilium,
        supports_calico=supports_calico,
    )


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
    runtime = package_runtime(installation, validate_paths=False)
    runtime_config = installation.runtime_config or {}
    command, args, cwd = kubernetes_runtime_process(runtime, runtime_config)
    command_parts = [command, *args]
    if cwd:
        command_parts = ["sh", "-lc", f"cd {shlex.quote(cwd)} && {shlex.join(command_parts)}"]
    if not runtime_gateway_image_override(runtime_config):
        command_parts = [
            "node",
            KUBERNETES_STRUCTURED_CONTENT_PROXY_PATH,
            "--",
            *command_parts,
        ]
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

def transport_process_command(transport: Any) -> tuple[str, list[str]]:
    if not isinstance(transport, dict):
        return "", []
    raw_args = transport.get("args")
    args = [str(arg) for arg in raw_args] if isinstance(raw_args, list) else []
    return str(transport.get("command") or "").strip(), args


def stdio_transport_command(transport: Any) -> tuple[str, list[str]]:
    if not isinstance(transport, dict):
        return "", []
    if str(transport.get("type") or "stdio").strip().lower() not in {"", "stdio"}:
        return "", []
    return transport_process_command(transport)


def is_package_native_http_runtime(runtime_config: dict[str, Any]) -> bool:
    return package_transport_type(runtime_config) == RUNTIME_TRANSPORT_STREAMABLE_HTTP


def npm_package_directory(identifier: str) -> str:
    return f"{KUBERNETES_NPM_PACKAGE_MOUNT_PATH}/node_modules/{identifier}"


def pypi_runtime_dependencies(runtime_config: dict[str, Any]) -> list[str]:
    sources: list[dict[str, Any]] = [runtime_config]
    package = runtime_config.get("package")
    if isinstance(package, dict):
        sources.append(package)
    return python_runtime_dependency_values(
        *sources,
        identifier=runtime_package_identifier(runtime_config),
        version=runtime_package_version(runtime_config),
    )

def pypi_runtime_dependency_args(runtime_config: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for dependency in pypi_runtime_dependencies(runtime_config):
        args.extend(["--with", dependency])
    return args


def package_python_version_args(runtime_config: dict[str, Any]) -> list[str]:
    identifier = runtime_package_identifier(runtime_config)
    version = runtime_package_version(runtime_config)
    package = runtime_config.get("package")
    sources = [runtime_config]
    if isinstance(package, dict):
        sources.append(package)
    for source in sources:
        requirement = resolve_python_runtime_requirement(
            source,
            identifier=identifier,
            version=version,
        )
        if requirement.python_version:
            return ["--python", requirement.python_version]
    return []


def add_python_version_args(
    args: list[str],
    runtime_config: dict[str, Any],
) -> list[str]:
    if "--python" in args:
        return args
    return [*package_python_version_args(runtime_config), *args]


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
    python_args = package_python_version_args(runtime_config)
    transport_command_name = Path(transport_command).name
    configured_args = trim_overlapping_process_args(transport_args, configured_args)
    if transport_command_name == "uvx" and transport_args:
        return [
            *python_args,
            "--from",
            package_spec,
            *dependency_args,
            *transport_args,
            *configured_args,
        ]
    if transport_command_name not in {"", "python", "python3"}:
        return [
            *python_args,
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
            rewrite_runtime_file_paths(
                add_python_version_args(runtime.args, runtime_config),
                runtime_config,
            ),
            "",
        )

    if package_registry_type == "npm" and identifier:
        if is_package_native_http_runtime(runtime_config):
            package = runtime_config.get("package")
            package_transport = package.get("transport") if isinstance(package, dict) else None
            transport_command, transport_args = transport_process_command(
                package_transport or runtime_config.get("transport")
            )
            command_name = Path(transport_command or runtime.command).name
            configured_args = transport_args if transport_command else runtime.args
            package_directory = npm_package_directory(identifier)
            if command_name == "npm":
                return (
                    "npm",
                    rewrite_runtime_file_paths(configured_args or ["start"], runtime_config),
                    package_directory,
                )
            if transport_command:
                return (
                    command_name,
                    rewrite_runtime_file_paths(configured_args, runtime_config),
                    package_directory,
                )

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
                    *package_python_version_args(runtime_config),
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
    container_command: list[str] | None = None,
    container_args: list[str],
    container_working_dir: str | None = None,
    container_env_values: dict[str, str] | None = None,
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
    explicit_env_vars = [
        client.V1EnvVar(name=name, value=value)
        for name, value in (container_env_values or {}).items()
    ]
    explicit_env_names = {env.name for env in explicit_env_vars}
    effective_secret_keys = [key for key in secret_keys if key not in explicit_env_names]
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
                    command=container_command,
                    args=container_args,
                    working_dir=container_working_dir,
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
                            keys=effective_secret_keys,
                            client_module=client,
                        ),
                        *explicit_env_vars,
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

def runtime_network_policy_names(names: KubernetesRuntimeNames) -> tuple[str, ...]:
    return (
        safe_kubernetes_name(f"{names.pod_name}-default-deny"),
        safe_kubernetes_name(f"{names.pod_name}-allow-wardn-ingress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-dns-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-public-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-private-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-kubernetes-api-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-custom-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-remote-mcp-egress"),
        safe_kubernetes_name(f"{names.pod_name}-allow-all-egress"),
    )


def runtime_custom_network_policy_refs(
    names: KubernetesRuntimeNames,
) -> tuple[KubernetesCustomNetworkPolicyRef, ...]:
    return (
        KubernetesCustomNetworkPolicyRef(
            group=CILIUM_NETWORK_POLICY_GROUP,
            version=CILIUM_NETWORK_POLICY_VERSION,
            plural=CILIUM_NETWORK_POLICY_PLURAL,
            kind=CILIUM_NETWORK_POLICY_KIND,
            name=safe_kubernetes_name(f"{names.pod_name}-allow-cilium-kube-api-egress"),
        ),
        KubernetesCustomNetworkPolicyRef(
            group=CALICO_NETWORK_POLICY_GROUP,
            version=CALICO_NETWORK_POLICY_VERSION,
            plural=CALICO_NETWORK_POLICY_PLURAL,
            kind=CALICO_NETWORK_POLICY_KIND,
            name=safe_kubernetes_name(f"{names.pod_name}-allow-calico-kube-api-egress"),
        ),
        KubernetesCustomNetworkPolicyRef(
            group=CILIUM_NETWORK_POLICY_GROUP,
            version=CILIUM_NETWORK_POLICY_VERSION,
            plural=CILIUM_NETWORK_POLICY_PLURAL,
            kind=CILIUM_NETWORK_POLICY_KIND,
            name=safe_kubernetes_name(f"{names.pod_name}-allow-cilium-remote-mcp-egress"),
        ),
        KubernetesCustomNetworkPolicyRef(
            group=CILIUM_NETWORK_POLICY_GROUP,
            version=CILIUM_NETWORK_POLICY_VERSION,
            plural=CILIUM_NETWORK_POLICY_PLURAL,
            kind=CILIUM_NETWORK_POLICY_KIND,
            name=safe_kubernetes_name(f"{names.pod_name}-allow-cilium-custom-egress"),
        ),
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


def build_allow_all_egress_network_policy(
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
            egress=[client.V1NetworkPolicyEgressRule()],
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
    network_discovery: KubernetesNetworkDiscovery | None = None,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    discovery = network_discovery or default_kubernetes_network_discovery()
    if discovery.dns_service_cidrs:
        destinations = [
            client.V1NetworkPolicyPeer(
                ip_block=client.V1IPBlock(cidr=cidr)
            )
            for cidr in discovery.dns_service_cidrs
        ]
    else:
        destinations = [
            client.V1NetworkPolicyPeer(
                namespace_selector=namespace_name_selector(
                    discovery.dns_namespace,
                    client_module=client,
                ),
                pod_selector=label_selector(discovery.dns_selector, client),
            )
        ]
    ports = [
        client.V1NetworkPolicyPort(protocol=protocol, port=port)
        for port in discovery.dns_ports
        for protocol in ("UDP", "TCP")
    ]
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
                    to=destinations,
                    ports=ports,
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


def build_ip_block_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    rules: list[dict[str, Any]],
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
                            ip_block=client.V1IPBlock(
                                cidr=rule["cidr"],
                                _except=rule.get("except") or None,
                            )
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(protocol="TCP", port=port)
                        for port in rule["ports"]
                    ],
                )
                for rule in rules
            ],
        ),
    )


def build_private_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    ports: list[int],
    client_module: Any | None = None,
) -> Any:
    return build_ip_block_egress_network_policy(
        names=names,
        labels=labels,
        policy_name=policy_name,
        rules=[{"cidr": cidr, "ports": ports} for cidr in RUNTIME_PRIVATE_EGRESS_CIDRS],
        client_module=client_module,
    )


def build_kubernetes_api_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    network_discovery: KubernetesNetworkDiscovery | None = None,
    client_module: Any | None = None,
) -> Any | None:
    discovery = network_discovery or default_kubernetes_network_discovery()
    if not discovery.kubernetes_api_cidrs:
        return None
    return build_ip_block_egress_network_policy(
        names=names,
        labels=labels,
        policy_name=policy_name,
        rules=[
            {"cidr": cidr, "ports": list(discovery.kubernetes_api_service_ports)}
            for cidr in discovery.kubernetes_api_cidrs
        ],
        client_module=client_module,
    )


def calico_label_selector(labels: dict[str, str]) -> str:
    return " && ".join(
        f"{key} == {json.dumps(value)}"
        for key, value in sorted(labels.items())
    )


def build_cilium_kubernetes_api_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_ref: KubernetesCustomNetworkPolicyRef,
    network_discovery: KubernetesNetworkDiscovery | None = None,
) -> KubernetesCustomNetworkPolicy:
    discovery = network_discovery or default_kubernetes_network_discovery()
    return KubernetesCustomNetworkPolicy(
        ref=policy_ref,
        body={
            "apiVersion": f"{policy_ref.group}/{policy_ref.version}",
            "kind": policy_ref.kind,
            "metadata": {
                "name": policy_ref.name,
                "namespace": names.namespace,
                "labels": labels,
            },
            "spec": {
                "endpointSelector": {
                    "matchLabels": service_selector(labels),
                },
                "egress": [
                    {
                        "toEntities": ["kube-apiserver"],
                        "toPorts": [
                            {
                                "ports": [
                                    {"port": str(port), "protocol": "TCP"}
                                    for port in discovery.kubernetes_api_endpoint_ports
                                ],
                            }
                        ],
                    }
                ],
            },
        },
    )


def build_calico_kubernetes_api_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_ref: KubernetesCustomNetworkPolicyRef,
) -> KubernetesCustomNetworkPolicy:
    return KubernetesCustomNetworkPolicy(
        ref=policy_ref,
        body={
            "apiVersion": f"{policy_ref.group}/{policy_ref.version}",
            "kind": policy_ref.kind,
            "metadata": {
                "name": policy_ref.name,
                "namespace": names.namespace,
                "labels": labels,
            },
            "spec": {
                "selector": calico_label_selector(service_selector(labels)),
                "types": ["Egress"],
                "egress": [
                    {
                        "action": "Allow",
                        "protocol": "TCP",
                        "destination": {
                            "services": {
                                "name": KUBERNETES_API_SERVICE_NAME,
                                "namespace": KUBERNETES_API_SERVICE_NAMESPACE,
                            }
                        },
                    }
                ],
            },
        },
    )


def network_policy_backend(
    discovery: KubernetesNetworkDiscovery | None,
    *,
    settings=None,
) -> str:
    override = cni_provider_from_network_policy_backend(
        configured_network_policy_backend(settings)
    )
    if override is not None:
        return override[0]
    if discovery is None:
        return KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD
    if discovery.supports_cilium:
        return KUBERNETES_NETWORK_POLICY_BACKEND_CILIUM
    if discovery.supports_calico:
        return KUBERNETES_NETWORK_POLICY_BACKEND_CALICO
    return KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD


def remote_destination_ip_block_rules(
    destinations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for destination in destinations:
        port = destination["port"]
        for cidr in destination.get("cidrs") or []:
            rules.append(
                {
                    "cidr": cidr,
                    "ports": [port],
                    "label": destination.get("label") or destination["host"],
                }
            )
    return rules


def build_remote_mcp_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    destinations: list[dict[str, Any]],
    client_module: Any | None = None,
) -> Any | None:
    rules = remote_destination_ip_block_rules(destinations)
    if not rules:
        return None
    return build_ip_block_egress_network_policy(
        names=names,
        labels=labels,
        policy_name=policy_name,
        rules=rules,
        client_module=client_module,
    )


def cilium_dns_egress_rule(
    network_discovery: KubernetesNetworkDiscovery | None,
) -> dict[str, Any]:
    discovery = network_discovery or default_kubernetes_network_discovery()
    match_labels = {
        f"k8s:{key}": value
        for key, value in discovery.dns_selector.items()
        if key and value
    }
    match_labels["k8s:io.kubernetes.pod.namespace"] = discovery.dns_namespace
    return {
        "toEndpoints": [{"matchLabels": match_labels}],
        "toPorts": [
            {
                "ports": [
                    {"port": str(port), "protocol": "ANY"}
                    for port in discovery.dns_ports
                ],
                "rules": {"dns": [{"matchPattern": "*"}]},
            }
        ],
    }


def build_cilium_remote_mcp_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_ref: KubernetesCustomNetworkPolicyRef,
    destinations: list[dict[str, Any]],
    network_discovery: KubernetesNetworkDiscovery | None = None,
) -> KubernetesCustomNetworkPolicy | None:
    egress: list[dict[str, Any]] = []
    has_fqdn_rule = False
    for destination in destinations:
        port_rule = {
            "toPorts": [
                {
                    "ports": [
                        {"port": str(destination["port"]), "protocol": "TCP"},
                    ],
                }
            ]
        }
        host = destination["host"]
        if ip_cidr_for_address(host) is None:
            has_fqdn_rule = True
            egress.append(
                {
                    "toFQDNs": [{"matchName": host}],
                    **port_rule,
                }
            )
            continue
        for cidr in destination.get("cidrs") or []:
            egress.append(
                {
                    "toCIDRSet": [{"cidr": cidr}],
                    **port_rule,
                }
            )
    if not egress:
        return None
    if has_fqdn_rule:
        egress.insert(0, cilium_dns_egress_rule(network_discovery))

    return KubernetesCustomNetworkPolicy(
        ref=policy_ref,
        body={
            "apiVersion": f"{policy_ref.group}/{policy_ref.version}",
            "kind": policy_ref.kind,
            "metadata": {
                "name": policy_ref.name,
                "namespace": names.namespace,
                "labels": labels,
            },
            "spec": {
                "endpointSelector": {
                    "matchLabels": service_selector(labels),
                },
                "egress": egress,
            },
        },
    )


def build_custom_network_policy_manifests(
    installation: MCPServerInstallation,
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    network_discovery: KubernetesNetworkDiscovery | None = None,
    settings=None,
) -> list[KubernetesCustomNetworkPolicy]:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_network_policy_enabled:
        return []
    policy_config = network_policy_config(installation, settings=runtime_settings)
    if not policy_config["isolationEnabled"]:
        return []

    backend = network_policy_backend(network_discovery, settings=runtime_settings)
    cilium_kube_ref, calico_kube_ref, cilium_remote_ref, cilium_custom_ref = (
        runtime_custom_network_policy_refs(names)
    )
    custom_policies: list[KubernetesCustomNetworkPolicy] = []
    if policy_config["allowKubernetesApi"] and backend == "cilium":
        custom_policies.append(
            build_cilium_kubernetes_api_egress_network_policy(
                names=names,
                labels=labels,
                policy_ref=cilium_kube_ref,
                network_discovery=network_discovery,
            )
        )
    elif policy_config["allowKubernetesApi"] and backend == "calico":
        custom_policies.append(
            build_calico_kubernetes_api_egress_network_policy(
                names=names,
                labels=labels,
                policy_ref=calico_kube_ref,
            )
        )

    if (
        policy_config["allowRemoteMcpEgress"]
        and backend == "cilium"
        and policy_config["remoteDestinations"]
    ):
        cilium_remote_policy = build_cilium_remote_mcp_egress_network_policy(
            names=names,
            labels=labels,
            policy_ref=cilium_remote_ref,
            destinations=policy_config["remoteDestinations"],
            network_discovery=network_discovery,
        )
        if cilium_remote_policy is not None:
            custom_policies.append(cilium_remote_policy)
    if backend == "cilium" and custom_egress_domain_rules(policy_config["customEgress"]):
        cilium_custom_policy = build_cilium_custom_egress_network_policy(
            names=names,
            labels=labels,
            policy_ref=cilium_custom_ref,
            rules=custom_egress_domain_rules(policy_config["customEgress"]),
            network_discovery=network_discovery,
        )
        if cilium_custom_policy is not None:
            custom_policies.append(cilium_custom_policy)
    return custom_policies


def standard_kubernetes_api_policy_allowed(
    policy_config: dict[str, Any],
    network_discovery: KubernetesNetworkDiscovery | None,
    *,
    settings=None,
) -> bool:
    return (
        bool(policy_config["allowKubernetesApi"])
        and network_policy_backend(network_discovery, settings=settings)
        == KUBERNETES_NETWORK_POLICY_BACKEND_STANDARD
    )


def build_custom_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_name: str,
    rules: list[dict[str, Any]],
    client_module: Any | None = None,
) -> Any:
    return build_ip_block_egress_network_policy(
        names=names,
        labels=labels,
        policy_name=policy_name,
        rules=rules,
        client_module=client_module,
    )


def custom_egress_domain_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        rule
        for rule in rules
        if rule.get("destinationType") == "domain" and str(rule.get("domain") or "").strip()
    ]


def custom_egress_ip_block_rules(
    rules: list[dict[str, Any]],
    *,
    resolve_domains: bool,
) -> list[dict[str, Any]]:
    ip_rules: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("destinationType") == "domain":
            if not resolve_domains:
                continue
            for cidr in resolve_remote_host_cidrs(rule["domain"]):
                ip_rules.append(
                    {
                        "label": rule.get("label") or rule["domain"],
                        "cidr": cidr,
                        "ports": rule["ports"],
                    }
                )
            continue
        ip_rules.append(
            {
                "label": rule.get("label") or rule["cidr"],
                "cidr": rule["cidr"],
                "ports": rule["ports"],
            }
        )
    return ip_rules


def build_cilium_custom_egress_network_policy(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    policy_ref: KubernetesCustomNetworkPolicyRef,
    rules: list[dict[str, Any]],
    network_discovery: KubernetesNetworkDiscovery | None = None,
) -> KubernetesCustomNetworkPolicy | None:
    egress = [
        {
            "toFQDNs": [{"matchName": rule["domain"]}],
            "toPorts": [
                {
                    "ports": [
                        {"port": str(port), "protocol": "TCP"}
                        for port in rule["ports"]
                    ],
                }
            ],
        }
        for rule in rules
    ]
    if not egress:
        return None
    egress.insert(0, cilium_dns_egress_rule(network_discovery))

    return KubernetesCustomNetworkPolicy(
        ref=policy_ref,
        body={
            "apiVersion": f"{policy_ref.group}/{policy_ref.version}",
            "kind": policy_ref.kind,
            "metadata": {
                "name": policy_ref.name,
                "namespace": names.namespace,
                "labels": labels,
            },
            "spec": {
                "endpointSelector": {
                    "matchLabels": service_selector(labels),
                },
                "egress": egress,
            },
        },
    )


def build_network_policy_manifests(
    installation: MCPServerInstallation,
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    gateway_port: int,
    network_discovery: KubernetesNetworkDiscovery | None = None,
    settings=None,
    client_module: Any | None = None,
) -> list[Any]:
    runtime_settings = settings or get_settings()
    if not runtime_settings.mcp_runtime_kubernetes_network_policy_enabled:
        return []
    policy_config = network_policy_config(installation, settings=runtime_settings)
    policy_names = runtime_network_policy_names(names)
    if not policy_config["isolationEnabled"]:
        return [
            build_allow_all_egress_network_policy(
                names=names,
                labels=labels,
                policy_name=policy_names[8],
                client_module=client_module,
            )
        ]

    client = kubernetes_client_module(client_module)
    backend = network_policy_backend(network_discovery, settings=runtime_settings)
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
            network_discovery=network_discovery,
            client_module=client,
        ),
    ]
    if policy_config["publicEgress"]:
        policies.append(
            build_public_egress_network_policy(
                names=names,
                labels=labels,
                policy_name=policy_names[3],
                settings=runtime_settings,
                client_module=client,
            )
        )
    if policy_config["privateEgress"]:
        policies.append(
            build_private_egress_network_policy(
                names=names,
                labels=labels,
                policy_name=policy_names[4],
                ports=policy_config["privateEgressPorts"],
                client_module=client,
            )
        )
    if standard_kubernetes_api_policy_allowed(
        policy_config,
        network_discovery,
        settings=runtime_settings,
    ):
        kubernetes_api_policy = build_kubernetes_api_egress_network_policy(
            names=names,
            labels=labels,
            policy_name=policy_names[5],
            network_discovery=network_discovery,
            client_module=client,
        )
        if kubernetes_api_policy is not None:
            policies.append(kubernetes_api_policy)
    if policy_config["customEgress"]:
        custom_ip_rules = custom_egress_ip_block_rules(
            policy_config["customEgress"],
            resolve_domains=backend != "cilium",
        )
        if custom_ip_rules:
            policies.append(
                build_custom_egress_network_policy(
                    names=names,
                    labels=labels,
                    policy_name=policy_names[6],
                    rules=custom_ip_rules,
                    client_module=client,
                )
            )
    if (
        policy_config["allowRemoteMcpEgress"]
        and backend != "cilium"
    ):
        remote_mcp_policy = build_remote_mcp_egress_network_policy(
            names=names,
            labels=labels,
            policy_name=policy_names[7],
            destinations=policy_config["remoteDestinations"],
            client_module=client,
        )
        if remote_mcp_policy is not None:
            policies.append(remote_mcp_policy)
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
    network_discovery: KubernetesNetworkDiscovery | None = None,
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
    container_command: list[str] | None = None
    container_args: list[str] = []
    container_working_dir: str | None = None
    container_env_values: dict[str, str] = {}
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
    elif is_package_native_http_runtime(runtime_config):
        runtime = package_runtime(installation, validate_paths=False)
        command, args, cwd = kubernetes_runtime_process(runtime, runtime_config)
        container_name = KUBERNETES_MCP_SERVER_CONTAINER_NAME
        container_image = supergateway_image(installation, settings=runtime_settings)
        container_command = [command]
        container_args = args
        container_working_dir = cwd or None
        container_env_values = {
            **package_transport_env_values(runtime_config),
            "PORT": str(runtime_settings.mcp_runtime_kubernetes_service_port),
        }
        health_path = None
    else:
        container_image = supergateway_image(installation, settings=runtime_settings)
        container_args = supergateway_container_args(
            installation,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
        )
    if not is_oci_runtime(runtime_config) and npm_package_volume_required(runtime_config):
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
        container_command=container_command,
        container_args=container_args,
        container_working_dir=container_working_dir,
        container_env_values=container_env_values,
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
            installation,
            names=names,
            labels=labels,
            gateway_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            network_discovery=network_discovery,
            settings=runtime_settings,
            client_module=client,
        ),
        custom_network_policies=build_custom_network_policy_manifests(
            installation,
            names=names,
            labels=labels,
            network_discovery=network_discovery,
            settings=runtime_settings,
        ),
        network_policy_cleanup_names=(
            list(runtime_network_policy_names(names))
            if has_explicit_network_policy_config(installation)
            else []
        ),
        custom_network_policy_cleanup_refs=(
            list(runtime_custom_network_policy_refs(names))
            if has_explicit_network_policy_config(installation)
            else []
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
