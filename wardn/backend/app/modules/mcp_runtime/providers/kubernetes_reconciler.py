import time
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.modules.mcp_runtime.providers.kubernetes_client import (
    get_gateway_health,
    runtime_service_endpoint_url,
)
from app.modules.mcp_runtime.providers.kubernetes_naming import runtime_ingress_endpoint_url
from app.modules.mcp_runtime.providers.kubernetes_types import (
    KUBERNETES_API_CONNECT_TIMEOUT_SECONDS,
    KUBERNETES_API_READ_TIMEOUT_SECONDS,
    KubernetesReconcileError,
    KubernetesReconcileResult,
    KubernetesRuntimeManifest,
    KubernetesRuntimeNames,
    KubernetesRuntimeNotReadyError,
)


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
