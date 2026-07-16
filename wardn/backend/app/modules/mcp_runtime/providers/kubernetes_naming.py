import hashlib
import json
import re
from uuid import UUID

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.providers.kubernetes_types import (
    KUBERNETES_DNS_LABEL_PATTERN,
    KUBERNETES_LABEL_VALUE_MAX_LENGTH,
    KUBERNETES_METADATA_KEY_NAME_PATTERN,
    KUBERNETES_NAME_MAX_LENGTH,
    KUBERNETES_RESERVED_METADATA_KEYS,
    KUBERNETES_RESERVED_METADATA_PREFIXES,
    KUBERNETES_SUPERGATEWAY_MCP_PATH,
    KubernetesImagePullSecretError,
    KubernetesIngressError,
    KubernetesMetadataError,
    KubernetesReconcileError,
    KubernetesRuntimeNames,
)


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
