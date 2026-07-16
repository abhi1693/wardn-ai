import importlib
import ssl
from http.client import HTTPException as HTTPClientException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.modules.mcp_runtime.providers.kubernetes_types import (
    KUBERNETES_SUPERGATEWAY_HEALTH_PATH,
    KUBERNETES_SUPERGATEWAY_MCP_PATH,
    KubernetesClientSet,
    KubernetesConfigError,
    KubernetesRuntimeNames,
    KubernetesRuntimeNotReadyError,
)


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

def kubernetes_client_module(client_module: Any | None = None) -> Any:
    return client_module or importlib.import_module("kubernetes.client")

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
