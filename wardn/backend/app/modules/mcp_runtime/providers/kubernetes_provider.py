from collections.abc import Callable
from threading import Event
from typing import Any

from app.core.config import get_settings
from app.core.outbound_http import OutboundURLPolicy, normalize_hostname
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
    secret_fingerprint_payload,
)
from app.modules.mcp_runtime.providers.kubernetes_client import KubernetesClientFactory
from app.modules.mcp_runtime.providers.kubernetes_manifest_builder import (
    build_runtime_manifests,
    discover_kubernetes_network,
    is_oci_runtime,
    is_package_native_http_runtime,
    kubernetes_runtime_process,
    oci_runtime_container_args,
    oci_runtime_image,
    runtime_request_headers,
    supergateway_image,
)
from app.modules.mcp_runtime.providers.kubernetes_naming import runtime_object_names_for_session
from app.modules.mcp_runtime.providers.kubernetes_reconciler import KubernetesRuntimeReconciler
from app.modules.mcp_runtime.providers.kubernetes_types import (
    KubernetesClientSet,
    KubernetesReconcileError,
    KubernetesRuntimeManifest,
)


def runtime_mcp_outbound_policy(
    manifest: KubernetesRuntimeManifest,
    *,
    service_port: int,
) -> OutboundURLPolicy | None:
    if manifest.ingress is not None:
        return None
    service_host = normalize_hostname(
        f"{manifest.names.service_name}.{manifest.names.namespace}.svc.cluster.local"
    )
    return OutboundURLPolicy(
        allow_http=True,
        allowed_ports=frozenset({service_port}),
        private_host_allowlist=frozenset({service_host}),
    )


def deployment_condition_message(deployment: Any) -> str:
    status = getattr(deployment, "status", None)
    if status is None:
        return ""
    for condition in getattr(status, "conditions", None) or []:
        condition_status = str(getattr(condition, "status", "") or "")
        if condition_status != "False":
            continue
        reason = str(getattr(condition, "reason", "") or "")
        message = str(getattr(condition, "message", "") or "")
        if reason or message:
            return ": ".join(part for part in (reason, message) if part)
    return str(getattr(status, "message", "") or "")


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
        elif is_package_native_http_runtime(runtime_config):
            runtime = package_runtime(installation, validate_paths=False)
            command, args, cwd = kubernetes_runtime_process(runtime, runtime_config)
            runtime_image = supergateway_image(installation, settings=settings)
            workload_runtime = "package-http"
        else:
            runtime = package_runtime(installation, validate_paths=False)
            command, args, cwd = kubernetes_runtime_process(runtime, runtime_config)
            runtime_image = supergateway_image(installation, settings=settings)
            workload_runtime = "supergateway"
        provider_config = {
            "installationRuntimeConfig": runtime_config,
            "workloadKind": "deployment",
            "workloadRuntime": workload_runtime,
            "objectIdentity": "runtime_config_fingerprint",
            "runtimeImage": runtime_image,
            "gatewayImage": settings.mcp_runtime_kubernetes_gateway_image,
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
        client_set = self._client_factory.load()
        network_discovery = discover_kubernetes_network(client_set)
        manifest = build_runtime_manifests(
            installation,
            runtime_session,
            network_discovery=network_discovery,
        )
        settings = get_settings()
        reconciler = self._new_reconciler(client_set)
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
            verify_tls=settings.mcp_runtime_kubernetes_ingress_tls_verify,
            outbound_policy=runtime_mcp_outbound_policy(
                manifest,
                service_port=settings.mcp_runtime_kubernetes_service_port,
            ),
        )

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        cancel_event: Event | None = None,
        cancel_reason: str = "Tool call cancelled.",
        request_meta: dict[str, Any] | None = None,
        progress_callback: mcp_client.MCPProgressCallback | None = None,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        if runtime_session is None:
            raise NotImplementedError(
                "kubernetes MCP runtime reconciliation requires a runtime session"
            )
        client_set = self._client_factory.load()
        network_discovery = discover_kubernetes_network(client_set)
        manifest = build_runtime_manifests(
            installation,
            runtime_session,
            network_discovery=network_discovery,
        )
        settings = get_settings()
        reconciler = self._new_reconciler(client_set)
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
            verify_tls=settings.mcp_runtime_kubernetes_ingress_tls_verify,
            outbound_policy=runtime_mcp_outbound_policy(
                manifest,
                service_port=settings.mcp_runtime_kubernetes_service_port,
            ),
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
        client_set = self._client_factory.load()
        network_discovery = discover_kubernetes_network(client_set)
        manifest = build_runtime_manifests(
            installation,
            runtime_session,
            network_discovery=network_discovery,
        )
        reconciler = self._new_reconciler(client_set)
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
        names = runtime_object_names_for_session(runtime_session, prefer_stored_names=True)
        try:
            deployment = self._new_reconciler().read_deployment(names)
        except KubernetesReconcileError as exc:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_NOT_READY,
                healthy=False,
                ready=False,
                message=str(exc),
                details={
                    "namespace": names.namespace,
                    "deploymentName": names.pod_name,
                },
            )

        spec = getattr(deployment, "spec", None)
        status = getattr(deployment, "status", None)
        desired = int(getattr(spec, "replicas", 1) or 1)
        ready = int(
            getattr(status, "ready_replicas", 0)
            or getattr(status, "available_replicas", 0)
            or 0
        )
        available = int(getattr(status, "available_replicas", 0) or 0)
        updated = int(getattr(status, "updated_replicas", 0) or 0)
        details = {
            "namespace": names.namespace,
            "deploymentName": names.pod_name,
            "desiredReplicas": desired,
            "readyReplicas": ready,
            "availableReplicas": available,
            "updatedReplicas": updated,
        }
        if ready >= desired:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_READY,
                healthy=True,
                ready=True,
                message="Kubernetes runtime deployment is ready.",
                details=details,
            )

        condition_message = deployment_condition_message(deployment)
        return RuntimeHealth(
            status=RUNTIME_HEALTH_NOT_READY,
            healthy=False,
            ready=False,
            message=condition_message
            or f"Kubernetes runtime deployment is not ready; ready={ready}, desired={desired}.",
            details=details,
        )

    def _new_reconciler(
        self,
        client_set: KubernetesClientSet | None = None,
    ) -> KubernetesRuntimeReconciler:
        client_set = client_set or self._client_factory.load()
        return self._reconciler_factory(
            core_v1=client_set.core_v1,
            apps_v1=client_set.apps_v1,
            networking_v1=client_set.networking_v1,
            custom_objects=getattr(client_set, "custom_objects", None),
            api_exception_class=self._client_factory.api_exception_class(),
        )
