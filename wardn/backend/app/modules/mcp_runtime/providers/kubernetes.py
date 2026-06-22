import hashlib
import importlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime import adapter_client
from app.modules.mcp_runtime.adapter_contract import (
    WARDN_RUNTIME_ARGS_JSON_ENV,
    WARDN_RUNTIME_COMMAND_ENV,
    WARDN_RUNTIME_CWD_ENV,
    WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV,
    WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_HEALTH_NOT_READY,
    RUNTIME_HEALTH_STOPPED,
    RUNTIME_KIND_PACKAGE,
    RUNTIME_PROVIDER_KUBERNETES,
    RUNTIME_TRANSPORT_STREAMABLE_HTTP,
    RuntimeHealth,
    RuntimeSpec,
    base_runtime_spec,
    package_runtime,
    runtime_kind,
)

KUBERNETES_LABEL_APP_NAME = "app.kubernetes.io/name"
KUBERNETES_LABEL_PART_OF = "app.kubernetes.io/part-of"
WARDN_LABEL_ORGANIZATION_ID = "wardn.ai/organization-id"
WARDN_LABEL_WORKSPACE_ID = "wardn.ai/workspace-id"
WARDN_LABEL_INSTALLATION_ID = "wardn.ai/installation-id"
WARDN_LABEL_RUNTIME_SESSION_ID = "wardn.ai/runtime-session-id"
WARDN_LABEL_SERVER_NAME = "wardn.ai/server-name"
WARDN_LABEL_SERVER_VERSION = "wardn.ai/server-version"
WARDN_RUNTIME_APP_NAME = "wardn-mcp-runtime"
KUBERNETES_NAME_MAX_LENGTH = 63
KUBERNETES_LABEL_VALUE_MAX_LENGTH = 63
KUBERNETES_ADAPTER_CONTAINER_NAME = "wardn-runtime-adapter"
KUBERNETES_ADAPTER_PORT_NAME = "http"


class KubernetesRuntimeProviderError(RuntimeError):
    pass


class KubernetesConfigError(KubernetesRuntimeProviderError):
    pass


class KubernetesReconcileError(KubernetesRuntimeProviderError):
    pass


class KubernetesRuntimeNotReadyError(KubernetesRuntimeProviderError):
    pass


@dataclass(frozen=True)
class KubernetesClientSet:
    core_v1: Any
    loaded_config: str


@dataclass(frozen=True)
class KubernetesRuntimeNames:
    namespace: str
    pod_name: str
    service_name: str
    secret_name: str


@dataclass(frozen=True)
class KubernetesRuntimeManifest:
    names: KubernetesRuntimeNames
    labels: dict[str, str]
    secret_data: dict[str, str]
    namespace: Any
    secret: Any
    pod: Any
    service: Any


@dataclass(frozen=True)
class KubernetesReconcileResult:
    endpoint_url: str
    pod: Any | None = None
    adapter_status: dict[str, Any] | None = None


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
    runtime_session_id: UUID | str,
    organization_id: UUID | str | None,
    workspace_id: UUID | str | None,
    prefix: str | None = None,
) -> KubernetesRuntimeNames:
    session_hash = short_hash(str(runtime_session_id), length=12)
    base_name = safe_kubernetes_name(f"mcp-{session_hash}")
    return KubernetesRuntimeNames(
        namespace=runtime_namespace_name(
            organization_id=organization_id,
            workspace_id=workspace_id,
            prefix=prefix,
        ),
        pod_name=safe_kubernetes_name(f"{base_name}-pod"),
        service_name=safe_kubernetes_name(f"{base_name}-svc"),
        secret_name=safe_kubernetes_name(f"{base_name}-secret"),
    )


def runtime_labels(
    *,
    organization_id: UUID | str | None,
    workspace_id: UUID | str | None,
    installation_id: UUID | str,
    runtime_session_id: UUID | str,
    server_name: str,
    server_version: str,
) -> dict[str, str]:
    labels = {
        KUBERNETES_LABEL_APP_NAME: WARDN_RUNTIME_APP_NAME,
        KUBERNETES_LABEL_PART_OF: "wardn",
        WARDN_LABEL_INSTALLATION_ID: str(installation_id),
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
    runtime = package_runtime(installation)
    runtime_settings = settings or get_settings()
    data = {
        WARDN_RUNTIME_COMMAND_ENV: runtime.command,
        WARDN_RUNTIME_ARGS_JSON_ENV: json.dumps(runtime.args, separators=(",", ":")),
        WARDN_RUNTIME_CWD_ENV: runtime.cwd,
        WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV: str(
            runtime_settings.mcp_runtime_adapter_startup_timeout_seconds
        ),
        WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV: str(
            runtime_settings.mcp_runtime_adapter_request_timeout_seconds
        ),
    }
    data.update(runtime.environment)
    return data


def build_namespace_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Namespace(
        metadata=client.V1ObjectMeta(
            name=names.namespace,
            labels={
                KUBERNETES_LABEL_PART_OF: "wardn",
                **labels,
            },
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


def build_pod_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    secret_keys: list[str],
    adapter_image: str,
    adapter_port: int,
    client_module: Any | None = None,
) -> Any:
    client = kubernetes_client_module(client_module)
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=names.pod_name,
            namespace=names.namespace,
            labels=labels,
        ),
        spec=client.V1PodSpec(
            automount_service_account_token=False,
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name=KUBERNETES_ADAPTER_CONTAINER_NAME,
                    image=adapter_image,
                    ports=[
                        client.V1ContainerPort(
                            container_port=adapter_port,
                            name=KUBERNETES_ADAPTER_PORT_NAME,
                        )
                    ],
                    env=secret_env_vars(
                        names=names,
                        keys=secret_keys,
                        client_module=client,
                    ),
                )
            ],
        ),
    )


def service_selector(labels: dict[str, str]) -> dict[str, str]:
    return {
        KUBERNETES_LABEL_APP_NAME: labels[KUBERNETES_LABEL_APP_NAME],
        WARDN_LABEL_RUNTIME_SESSION_ID: labels[WARDN_LABEL_RUNTIME_SESSION_ID],
    }


def build_service_manifest(
    *,
    names: KubernetesRuntimeNames,
    labels: dict[str, str],
    adapter_port: int,
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
                    name=KUBERNETES_ADAPTER_PORT_NAME,
                    port=adapter_port,
                    target_port=adapter_port,
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
    names = runtime_object_names(
        runtime_session_id=runtime_session.id,
        organization_id=runtime_session.organization_id,
        workspace_id=runtime_session.workspace_id,
        prefix=runtime_settings.mcp_runtime_kubernetes_namespace_prefix,
    )
    labels = runtime_labels(
        organization_id=runtime_session.organization_id,
        workspace_id=runtime_session.workspace_id,
        installation_id=runtime_session.installation_id,
        runtime_session_id=runtime_session.id,
        server_name=runtime_session.server_name,
        server_version=runtime_session.server_version,
    )
    secret_data = runtime_secret_data(installation, settings=runtime_settings)
    client = kubernetes_client_module(client_module)
    return KubernetesRuntimeManifest(
        names=names,
        labels=labels,
        secret_data=secret_data,
        namespace=build_namespace_manifest(names=names, labels=labels, client_module=client),
        secret=build_secret_manifest(
            names=names,
            labels=labels,
            string_data=secret_data,
            client_module=client,
        ),
        pod=build_pod_manifest(
            names=names,
            labels=labels,
            secret_keys=list(secret_data),
            adapter_image=runtime_settings.mcp_runtime_kubernetes_adapter_image,
            adapter_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            client_module=client,
        ),
        service=build_service_manifest(
            names=names,
            labels=labels,
            adapter_port=runtime_settings.mcp_runtime_kubernetes_service_port,
            client_module=client,
        ),
    )


def runtime_service_endpoint_url(
    *,
    names: KubernetesRuntimeNames,
    adapter_port: int,
) -> str:
    return f"http://{names.service_name}.{names.namespace}.svc.cluster.local:{adapter_port}"


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
        api_exception_class: type[Exception],
        settings=None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.core_v1 = core_v1
        self.api_exception_class = api_exception_class
        self.settings = settings or get_settings()
        self.sleep = sleep
        self.monotonic = monotonic

    def reconcile(self, manifest: KubernetesRuntimeManifest) -> KubernetesReconcileResult:
        self.create_namespace(manifest)
        self.create_or_replace_secret(manifest)
        self.create_pod(manifest)
        self.create_or_replace_service(manifest)
        return KubernetesReconcileResult(
            endpoint_url=runtime_service_endpoint_url(
                names=manifest.names,
                adapter_port=self.settings.mcp_runtime_kubernetes_service_port,
            )
        )

    def create_namespace(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self.core_v1.create_namespace(body=manifest.namespace)
        except self.api_exception_class as exc:
            if self._is_status(exc, 409):
                return
            raise KubernetesReconcileError(
                f"Kubernetes namespace reconcile failed: {self._api_error_detail(exc)}"
            ) from exc

    def create_or_replace_secret(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self.core_v1.create_namespaced_secret(
                namespace=manifest.names.namespace,
                body=manifest.secret,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes secret reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self.core_v1.replace_namespaced_secret(
                    name=manifest.names.secret_name,
                    namespace=manifest.names.namespace,
                    body=manifest.secret,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    f"Kubernetes secret replace failed: {self._api_error_detail(replace_exc)}"
                ) from replace_exc

    def create_pod(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self.core_v1.create_namespaced_pod(
                namespace=manifest.names.namespace,
                body=manifest.pod,
            )
        except self.api_exception_class as exc:
            if self._is_status(exc, 409):
                return
            raise KubernetesReconcileError(
                f"Kubernetes pod reconcile failed: {self._api_error_detail(exc)}"
            ) from exc

    def create_or_replace_service(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self.core_v1.create_namespaced_service(
                namespace=manifest.names.namespace,
                body=manifest.service,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes service reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self.core_v1.replace_namespaced_service(
                    name=manifest.names.service_name,
                    namespace=manifest.names.namespace,
                    body=manifest.service,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    f"Kubernetes service replace failed: {self._api_error_detail(replace_exc)}"
                ) from replace_exc

    def read_pod(self, names: KubernetesRuntimeNames) -> Any:
        try:
            return self.core_v1.read_namespaced_pod(
                name=names.pod_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            raise KubernetesReconcileError(
                f"Kubernetes pod read failed: {self._api_error_detail(exc)}"
            ) from exc

    def wait_for_pod_ready(
        self,
        names: KubernetesRuntimeNames,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 1,
    ) -> Any:
        deadline = self.monotonic() + (
            timeout_seconds or self.settings.mcp_runtime_adapter_startup_timeout_seconds
        )
        last_phase = ""
        while self.monotonic() < deadline:
            pod = self.read_pod(names)
            status = getattr(pod, "status", None)
            last_phase = str(getattr(status, "phase", "") if status is not None else "")
            if pod_is_ready(pod):
                return pod
            if last_phase in {"Failed", "Succeeded"}:
                suffix = pod_failure_message(pod)
                detail = f": {suffix}" if suffix else ""
                raise KubernetesRuntimeNotReadyError(
                    f"Kubernetes runtime pod reached terminal phase {last_phase}{detail}"
                )
            self.sleep(poll_interval_seconds)
        raise KubernetesRuntimeNotReadyError(
            f"Kubernetes runtime pod did not become ready; last phase={last_phase or 'unknown'}"
        )

    def wait_for_adapter_ready(
        self,
        endpoint_url: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 1,
    ) -> dict[str, Any]:
        deadline = self.monotonic() + (
            timeout_seconds or self.settings.mcp_runtime_adapter_startup_timeout_seconds
        )
        last_error = ""
        while self.monotonic() < deadline:
            try:
                status_payload = adapter_client.get_adapter_status(endpoint_url)
                if status_payload.get("ready") is True:
                    return status_payload
                last_error = str(status_payload)
            except adapter_client.MCPRuntimeAdapterError as exc:
                last_error = str(exc)
            self.sleep(poll_interval_seconds)
        raise KubernetesRuntimeNotReadyError(
            f"Kubernetes runtime adapter did not become ready: {last_error}"
        )

    def wait_until_ready(
        self,
        manifest: KubernetesRuntimeManifest,
        *,
        endpoint_url: str,
    ) -> KubernetesReconcileResult:
        pod = self.wait_for_pod_ready(manifest.names)
        adapter_status = self.wait_for_adapter_ready(endpoint_url)
        return KubernetesReconcileResult(
            endpoint_url=endpoint_url,
            pod=pod,
            adapter_status=adapter_status,
        )

    def _is_status(self, exc: Exception, status_code: int) -> bool:
        return int(getattr(exc, "status", 0) or 0) == status_code

    def _api_error_detail(self, exc: Exception) -> str:
        status = getattr(exc, "status", None)
        reason = getattr(exc, "reason", "")
        body = getattr(exc, "body", "")
        parts = [str(item) for item in (status, reason, body) if item]
        return " ".join(parts) or str(exc)


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
        runtime = package_runtime(installation)
        return base_runtime_spec(
            installation,
            provider_name=self.name,
            transport=RUNTIME_TRANSPORT_STREAMABLE_HTTP,
            command=runtime.command,
            args=runtime.args,
            cwd=runtime.cwd,
        )

    def list_tools(self, installation: MCPServerInstallation) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "kubernetes MCP runtime tool discovery requires a runtime session; "
            "use a tracked runtime call path before adapter invocation is wired"
        )

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
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
        raise NotImplementedError(
            "kubernetes MCP runtime adapter HTTP invocation is not wired yet"
        )

    def stop_runtime(self, runtime_session: MCPRuntimeSession) -> None:
        return None

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
            api_exception_class=self._client_factory.api_exception_class(),
        )
