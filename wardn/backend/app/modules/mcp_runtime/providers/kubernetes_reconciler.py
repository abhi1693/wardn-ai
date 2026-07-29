import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.modules.mcp_runtime.providers.kubernetes_client import (
    get_gateway_health,
    runtime_service_endpoint_url,
)
from app.modules.mcp_runtime.providers.kubernetes_manifest_builder import (
    runtime_network_policy_names,
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

logger = logging.getLogger(__name__)


def kubernetes_runtime_log_extra(
    names: KubernetesRuntimeNames,
    *,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    action: str | None = None,
) -> dict[str, str | None]:
    return {
        "kubernetes_namespace": names.namespace,
        "kubernetes_pod_name": names.pod_name,
        "kubernetes_service_name": names.service_name,
        "kubernetes_ingress_name": names.ingress_name,
        "kubernetes_resource_kind": resource_kind,
        "kubernetes_resource_name": resource_name,
        "kubernetes_action": action,
    }


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
        logger.info(
            "Reconciling Kubernetes MCP runtime.",
            extra={
                **kubernetes_runtime_log_extra(manifest.names),
                "kubernetes_network_policy_count": len(manifest.network_policies),
                "kubernetes_ingress_enabled": manifest.ingress is not None,
            },
        )
        self.create_namespace(manifest)
        self.create_or_replace_network_policies(manifest)
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
        logger.info(
            "Reconciled Kubernetes MCP runtime.",
            extra={
                **kubernetes_runtime_log_extra(manifest.names),
                "mcp_runtime_endpoint_url": endpoint_url,
            },
        )
        return KubernetesReconcileResult(
            endpoint_url=endpoint_url,
        )

    def create_namespace(self, manifest: KubernetesRuntimeManifest) -> None:
        try:
            self._call_api(self.core_v1.create_namespace, body=manifest.namespace)
        except self.api_exception_class as exc:
            if self._is_status(exc, 409):
                logger.info(
                    "Kubernetes MCP runtime namespace already exists.",
                    extra=kubernetes_runtime_log_extra(
                        manifest.names,
                        resource_kind="Namespace",
                        resource_name=manifest.names.namespace,
                        action="exists",
                    ),
                )
                return
            raise KubernetesReconcileError(
                f"Kubernetes namespace reconcile failed: {self._api_error_detail(exc)}"
            ) from exc
        logger.info(
            "Created Kubernetes MCP runtime namespace.",
            extra=kubernetes_runtime_log_extra(
                manifest.names,
                resource_kind="Namespace",
                resource_name=manifest.names.namespace,
                action="create",
            ),
        )

    def create_or_replace_network_policies(self, manifest: KubernetesRuntimeManifest) -> None:
        for network_policy in manifest.network_policies:
            self.create_or_replace_network_policy(manifest, network_policy)

    def create_or_replace_network_policy(
        self,
        manifest: KubernetesRuntimeManifest,
        network_policy: Any,
    ) -> None:
        policy_name = network_policy.metadata.name
        try:
            self._call_api(
                self.networking_v1.create_namespaced_network_policy,
                namespace=manifest.names.namespace,
                body=network_policy,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 409):
                raise KubernetesReconcileError(
                    f"Kubernetes network policy reconcile failed: {self._api_error_detail(exc)}"
                ) from exc
            try:
                self._call_api(
                    self.networking_v1.replace_namespaced_network_policy,
                    name=policy_name,
                    namespace=manifest.names.namespace,
                    body=network_policy,
                )
            except self.api_exception_class as replace_exc:
                raise KubernetesReconcileError(
                    "Kubernetes network policy replace failed: "
                    f"{self._api_error_detail(replace_exc)}"
                ) from replace_exc
            logger.info(
                "Replaced Kubernetes MCP runtime NetworkPolicy.",
                extra=kubernetes_runtime_log_extra(
                    manifest.names,
                    resource_kind="NetworkPolicy",
                    resource_name=policy_name,
                    action="replace",
                ),
            )
            return
        logger.info(
            "Created Kubernetes MCP runtime NetworkPolicy.",
            extra=kubernetes_runtime_log_extra(
                manifest.names,
                resource_kind="NetworkPolicy",
                resource_name=policy_name,
                action="create",
            ),
        )

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
            logger.info(
                "Replaced Kubernetes MCP runtime Secret.",
                extra=kubernetes_runtime_log_extra(
                    manifest.names,
                    resource_kind="Secret",
                    resource_name=manifest.names.secret_name,
                    action="replace",
                ),
            )
            return
        logger.info(
            "Created Kubernetes MCP runtime Secret.",
            extra=kubernetes_runtime_log_extra(
                manifest.names,
                resource_kind="Secret",
                resource_name=manifest.names.secret_name,
                action="create",
            ),
        )

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
            logger.info(
                "Replaced Kubernetes MCP runtime Deployment.",
                extra=kubernetes_runtime_log_extra(
                    manifest.names,
                    resource_kind="Deployment",
                    resource_name=manifest.names.pod_name,
                    action="replace",
                ),
            )
            return
        logger.info(
            "Created Kubernetes MCP runtime Deployment.",
            extra=kubernetes_runtime_log_extra(
                manifest.names,
                resource_kind="Deployment",
                resource_name=manifest.names.pod_name,
                action="create",
            ),
        )

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
            logger.info(
                "Replaced Kubernetes MCP runtime Service.",
                extra=kubernetes_runtime_log_extra(
                    manifest.names,
                    resource_kind="Service",
                    resource_name=manifest.names.service_name,
                    action="replace",
                ),
            )
            return
        logger.info(
            "Created Kubernetes MCP runtime Service.",
            extra=kubernetes_runtime_log_extra(
                manifest.names,
                resource_kind="Service",
                resource_name=manifest.names.service_name,
                action="create",
            ),
        )

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
            logger.info(
                "Replaced Kubernetes MCP runtime Ingress.",
                extra=kubernetes_runtime_log_extra(
                    manifest.names,
                    resource_kind="Ingress",
                    resource_name=manifest.names.ingress_name,
                    action="replace",
                ),
            )
            return
        logger.info(
            "Created Kubernetes MCP runtime Ingress.",
            extra=kubernetes_runtime_log_extra(
                manifest.names,
                resource_kind="Ingress",
                resource_name=manifest.names.ingress_name,
                action="create",
            ),
        )

    def delete_runtime_objects(
        self,
        names: KubernetesRuntimeNames,
        *,
        delete_resources: bool = False,
    ) -> None:
        if not delete_resources:
            logger.info(
                "Scaling Kubernetes MCP runtime deployment to stop runtime.",
                extra={
                    **kubernetes_runtime_log_extra(
                        names,
                        resource_kind="Deployment",
                        resource_name=names.pod_name,
                        action="scale",
                    ),
                    "kubernetes_replicas": 0,
                },
            )
            self.scale_deployment(names, replicas=0)
            return
        logger.info(
            "Deleting Kubernetes MCP runtime resources.",
            extra=kubernetes_runtime_log_extra(names, action="delete"),
        )
        self.delete_ingress(names)
        self.delete_network_policies(names)
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
            return
        logger.info(
            "Deleted Kubernetes MCP runtime Ingress.",
            extra=kubernetes_runtime_log_extra(
                names,
                resource_kind="Ingress",
                resource_name=names.ingress_name,
                action="delete",
            ),
        )

    def delete_network_policies(self, names: KubernetesRuntimeNames) -> None:
        for policy_name in runtime_network_policy_names(names):
            self.delete_network_policy(names, policy_name)

    def delete_network_policy(self, names: KubernetesRuntimeNames, policy_name: str) -> None:
        try:
            self._call_api(
                self.networking_v1.delete_namespaced_network_policy,
                name=policy_name,
                namespace=names.namespace,
            )
        except self.api_exception_class as exc:
            if not self._is_status(exc, 404):
                raise KubernetesReconcileError(
                    f"Kubernetes network policy delete failed: {self._api_error_detail(exc)}"
                ) from exc
            return
        logger.info(
            "Deleted Kubernetes MCP runtime NetworkPolicy.",
            extra=kubernetes_runtime_log_extra(
                names,
                resource_kind="NetworkPolicy",
                resource_name=policy_name,
                action="delete",
            ),
        )

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
            return
        logger.info(
            "Deleted Kubernetes MCP runtime Service.",
            extra=kubernetes_runtime_log_extra(
                names,
                resource_kind="Service",
                resource_name=names.service_name,
                action="delete",
            ),
        )

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
            return
        logger.info(
            "Scaled Kubernetes MCP runtime Deployment.",
            extra={
                **kubernetes_runtime_log_extra(
                    names,
                    resource_kind="Deployment",
                    resource_name=names.pod_name,
                    action="scale",
                ),
                "kubernetes_replicas": replicas,
            },
        )

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
            return
        logger.info(
            "Deleted Kubernetes MCP runtime Deployment.",
            extra=kubernetes_runtime_log_extra(
                names,
                resource_kind="Deployment",
                resource_name=names.pod_name,
                action="delete",
            ),
        )

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
            return
        logger.info(
            "Deleted Kubernetes MCP runtime Secret.",
            extra=kubernetes_runtime_log_extra(
                names,
                resource_kind="Secret",
                resource_name=names.secret_name,
                action="delete",
            ),
        )

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
