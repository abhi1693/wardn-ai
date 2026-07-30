import uuid
from collections import deque

import pytest

from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.manager import (
    RUNTIME_KIND_PACKAGE,
    RUNTIME_PROVIDER_KUBERNETES,
    RUNTIME_TRANSPORT_STDIO,
    RUNTIME_TRANSPORT_STREAMABLE_HTTP,
    WARDN_CUSTOM_HEADERS_ENV,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.providers.kubernetes import (
    KUBERNETES_LABEL_APP_NAME,
    WARDN_LABEL_INSTALLATION_ID,
    WARDN_LABEL_RUNTIME_ID,
    WARDN_LABEL_RUNTIME_SESSION_ID,
    WARDN_LABEL_SERVER_NAME,
    WARDN_LABEL_WORKSPACE_ID,
    WARDN_RUNTIME_CONFIG_CHECKSUM_ANNOTATION,
    WARDN_RUNTIME_SECRET_CHECKSUM_ANNOTATION,
    KubernetesClientFactory,
    KubernetesConfigError,
    KubernetesImagePullSecretError,
    KubernetesIngressError,
    KubernetesMetadataError,
    KubernetesReconcileError,
    KubernetesReconcileResult,
    KubernetesRuntimeNotReadyError,
    KubernetesRuntimeProvider,
    KubernetesRuntimeReconciler,
    build_runtime_manifests,
    runtime_installation_identity,
    runtime_labels,
    runtime_namespace_name,
    runtime_network_policy_names,
    runtime_object_base_name,
    runtime_object_identity,
    runtime_object_names,
    runtime_object_names_for_session,
    runtime_request_headers,
    runtime_service_endpoint_url,
    safe_kubernetes_name,
)


class FakeKubernetesConfig:
    def __init__(self, *, in_cluster_error: Exception | None = None) -> None:
        self.in_cluster_error = in_cluster_error
        self.loaded: list[tuple[str, dict]] = []

    def load_incluster_config(self) -> None:
        self.loaded.append(("in_cluster", {}))
        if self.in_cluster_error is not None:
            raise self.in_cluster_error

    def load_kube_config(self, **kwargs) -> None:
        self.loaded.append(("kubeconfig", kwargs))


class FakeSettings:
    mcp_runtime_kubernetes_allow_kubeconfig = True
    mcp_runtime_kubernetes_kubeconfig_path = "/tmp/kubeconfig"
    mcp_runtime_kubernetes_context = "local"
    mcp_runtime_kubernetes_namespace_prefix = "wardn"
    mcp_runtime_kubernetes_gateway_image = "registry.example/supergateway:test"
    mcp_runtime_kubernetes_gateway_uvx_image = "registry.example/supergateway:test"
    mcp_runtime_kubernetes_gateway_deno_image = "registry.example/supergateway:test"
    mcp_runtime_kubernetes_cpu_request = "100m"
    mcp_runtime_kubernetes_cpu_limit = "1"
    mcp_runtime_kubernetes_memory_request = "256Mi"
    mcp_runtime_kubernetes_memory_limit = "1Gi"
    mcp_runtime_kubernetes_service_port = 8000
    mcp_runtime_kubernetes_sandbox_enabled = True
    mcp_runtime_kubernetes_runtime_class_name = ""
    mcp_runtime_kubernetes_run_as_user = 1000
    mcp_runtime_kubernetes_run_as_group = 1000
    mcp_runtime_kubernetes_read_only_root_filesystem = True
    mcp_runtime_kubernetes_tmp_size_limit = "512Mi"
    mcp_runtime_kubernetes_network_policy_enabled = True
    mcp_runtime_kubernetes_allow_public_egress = True
    mcp_runtime_kubernetes_public_egress_ports = [80, 443]
    mcp_runtime_kubernetes_control_plane_namespace = "wardn"
    mcp_runtime_kubernetes_control_plane_pod_selector_json = (
        '{"app.kubernetes.io/part-of":"wardn-ai"}'
    )
    mcp_runtime_kubernetes_image_pull_secret_name = ""
    mcp_runtime_kubernetes_namespace_labels_json = "{}"
    mcp_runtime_kubernetes_namespace_annotations_json = "{}"
    mcp_runtime_kubernetes_ingress_enabled = False
    mcp_runtime_kubernetes_ingress_base_domain = ""
    mcp_runtime_kubernetes_ingress_class_name = "traefik"
    mcp_runtime_kubernetes_ingress_scheme = "https"
    mcp_runtime_kubernetes_ingress_tls_verify = True
    mcp_runtime_kubernetes_ingress_tls_secret_name = ""
    mcp_runtime_kubernetes_ingress_traefik_entrypoints = "websecure"
    mcp_runtime_kubernetes_ingress_external_dns_enabled = True
    mcp_runtime_kubernetes_ingress_annotations_json = "{}"
    mcp_runtime_kubernetes_probe_enabled = True
    mcp_runtime_kubernetes_probe_period_seconds = 10
    mcp_runtime_kubernetes_probe_timeout_seconds = 3
    mcp_runtime_kubernetes_readiness_initial_delay_seconds = 2
    mcp_runtime_kubernetes_liveness_initial_delay_seconds = 30
    mcp_runtime_kubernetes_startup_failure_threshold = 180
    mcp_runtime_kubernetes_startup_timeout_seconds = 7
    mcp_runtime_kubernetes_api_timeout_seconds = 10


class CustomNamespaceMetadataSettings(FakeSettings):
    mcp_runtime_kubernetes_namespace_labels_json = (
        '{"billing.example.com/team":"runtime","environment":"dev"}'
    )
    mcp_runtime_kubernetes_namespace_annotations_json = (
        '{"owner.example.com/team":"platform","notes":"runtime namespace"}'
    )


class ImagePullSecretSettings(FakeSettings):
    mcp_runtime_kubernetes_image_pull_secret_name = "registry-credentials"


class IngressSettings(FakeSettings):
    mcp_runtime_kubernetes_ingress_enabled = True
    mcp_runtime_kubernetes_ingress_base_domain = "mcp.example.com"
    mcp_runtime_kubernetes_ingress_tls_secret_name = "mcp-tls"
    mcp_runtime_kubernetes_ingress_annotations_json = '{"example.com/owner":"wardn"}'


class IngressUnverifiedTlsSettings(IngressSettings):
    mcp_runtime_kubernetes_ingress_tls_verify = False


class DisabledProbeSettings(FakeSettings):
    mcp_runtime_kubernetes_probe_enabled = False


class FakeKubernetesModel:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeKubernetesClient:
    V1Capabilities = FakeKubernetesModel
    V1Container = FakeKubernetesModel
    V1ContainerPort = FakeKubernetesModel
    V1Deployment = FakeKubernetesModel
    V1DeploymentSpec = FakeKubernetesModel
    V1EmptyDirVolumeSource = FakeKubernetesModel
    V1EnvVar = FakeKubernetesModel
    V1EnvVarSource = FakeKubernetesModel
    V1HTTPIngressRuleValue = FakeKubernetesModel
    V1HTTPIngressPath = FakeKubernetesModel
    V1HTTPGetAction = FakeKubernetesModel
    V1LabelSelector = FakeKubernetesModel
    V1LocalObjectReference = FakeKubernetesModel
    V1Ingress = FakeKubernetesModel
    V1IngressBackend = FakeKubernetesModel
    V1IngressRule = FakeKubernetesModel
    V1IngressServiceBackend = FakeKubernetesModel
    V1IngressSpec = FakeKubernetesModel
    V1IngressTLS = FakeKubernetesModel
    V1IPBlock = FakeKubernetesModel
    V1Namespace = FakeKubernetesModel
    V1NetworkPolicy = FakeKubernetesModel
    V1NetworkPolicyEgressRule = FakeKubernetesModel
    V1NetworkPolicyIngressRule = FakeKubernetesModel
    V1NetworkPolicyPeer = FakeKubernetesModel
    V1NetworkPolicyPort = FakeKubernetesModel
    V1NetworkPolicySpec = FakeKubernetesModel
    V1ObjectMeta = FakeKubernetesModel
    V1Pod = FakeKubernetesModel
    V1PodSecurityContext = FakeKubernetesModel
    V1PodSpec = FakeKubernetesModel
    V1PodTemplateSpec = FakeKubernetesModel
    V1Probe = FakeKubernetesModel
    V1ResourceRequirements = FakeKubernetesModel
    V1SeccompProfile = FakeKubernetesModel
    V1Secret = FakeKubernetesModel
    V1SecretKeySelector = FakeKubernetesModel
    V1SecretVolumeSource = FakeKubernetesModel
    V1SecurityContext = FakeKubernetesModel
    V1Service = FakeKubernetesModel
    V1ServiceBackendPort = FakeKubernetesModel
    V1ServicePort = FakeKubernetesModel
    V1ServiceSpec = FakeKubernetesModel
    V1KeyToPath = FakeKubernetesModel
    V1Volume = FakeKubernetesModel
    V1VolumeMount = FakeKubernetesModel


class FakeApiException(Exception):
    def __init__(self, status: int, reason: str = "", body: str = "") -> None:
        self.status = status
        self.reason = reason
        self.body = body
        super().__init__(reason or str(status))


class FakeCoreV1Api:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.conflicts: set[str] = set()
        self.errors: dict[str, FakeApiException] = {}
        self.namespaces: set[str] = set()
        self.pods: deque = deque()
        self.deployments: deque = deque()

    def _call(self, method: str, name: str = "", namespace: str = "") -> None:
        self.calls.append((method, name, namespace))
        if method in self.errors:
            raise self.errors[method]
        if method in self.conflicts:
            raise FakeApiException(409, "AlreadyExists")

    def create_namespace(self, *, body):
        self._call("create_namespace", body.metadata.name, "")
        self.namespaces.add(body.metadata.name)

    def read_namespace(self, *, name):
        self._call("read_namespace", name, "")
        if name not in self.namespaces:
            raise FakeApiException(404, "NotFound")
        return FakeKubernetesModel(metadata=FakeKubernetesModel(name=name))

    def create_namespaced_secret(self, *, namespace, body):
        self._call("create_namespaced_secret", body.metadata.name, namespace)

    def replace_namespaced_secret(self, *, name, namespace, body):
        self._call("replace_namespaced_secret", name, namespace)

    def create_namespaced_service(self, *, namespace, body):
        self._call("create_namespaced_service", body.metadata.name, namespace)

    def replace_namespaced_service(self, *, name, namespace, body):
        self._call("replace_namespaced_service", name, namespace)

    def delete_namespaced_service(self, *, name, namespace):
        self._call("delete_namespaced_service", name, namespace)

    def delete_namespaced_secret(self, *, name, namespace):
        self._call("delete_namespaced_secret", name, namespace)

    def read_namespaced_pod(self, *, name, namespace):
        self._call("read_namespaced_pod", name, namespace)
        return self.pods.popleft()

    def create_namespaced_deployment(self, *, namespace, body):
        self._call("create_namespaced_deployment", body.metadata.name, namespace)

    def replace_namespaced_deployment(self, *, name, namespace, body):
        self._call("replace_namespaced_deployment", name, namespace)

    def patch_namespaced_deployment_scale(self, *, name, namespace, body):
        self._call("patch_namespaced_deployment_scale", name, namespace)

    def delete_namespaced_deployment(self, *, name, namespace):
        self._call("delete_namespaced_deployment", name, namespace)

    def read_namespaced_deployment(self, *, name, namespace):
        self._call("read_namespaced_deployment", name, namespace)
        return self.deployments.popleft()

    def create_namespaced_ingress(self, *, namespace, body):
        self._call("create_namespaced_ingress", body.metadata.name, namespace)

    def replace_namespaced_ingress(self, *, name, namespace, body):
        self._call("replace_namespaced_ingress", name, namespace)

    def delete_namespaced_ingress(self, *, name, namespace):
        self._call("delete_namespaced_ingress", name, namespace)

    def create_namespaced_network_policy(self, *, namespace, body):
        self._call("create_namespaced_network_policy", body.metadata.name, namespace)

    def replace_namespaced_network_policy(self, *, name, namespace, body):
        self._call("replace_namespaced_network_policy", name, namespace)

    def delete_namespaced_network_policy(self, *, name, namespace):
        self._call("delete_namespaced_network_policy", name, namespace)


class FakeClientSet:
    def __init__(self, core_v1) -> None:
        self.core_v1 = core_v1
        self.apps_v1 = core_v1
        self.networking_v1 = core_v1
        self.loaded_config = "in_cluster"


class FakeClientFactory:
    def __init__(self, core_v1) -> None:
        self.core_v1 = core_v1
        self.load_count = 0

    def load(self):
        self.load_count += 1
        return FakeClientSet(self.core_v1)

    def api_exception_class(self):
        return FakeApiException


class FakeReconciler:
    def __init__(
        self,
        *,
        core_v1,
        api_exception_class,
        apps_v1=None,
        networking_v1=None,
    ) -> None:
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1
        self.networking_v1 = networking_v1
        self.api_exception_class = api_exception_class
        self.reconciled_manifest = None
        self.ready_endpoint_url = ""

    def reconcile(self, manifest):
        self.reconciled_manifest = manifest
        return KubernetesReconcileResult(
            endpoint_url=runtime_service_endpoint_url(
                names=manifest.names,
                gateway_port=FakeSettings.mcp_runtime_kubernetes_service_port,
            )
        )

    def wait_until_ready(self, manifest, *, endpoint_url):
        self.ready_endpoint_url = endpoint_url
        return KubernetesReconcileResult(
            endpoint_url=endpoint_url,
            pod=FakeKubernetesModel(),
            gateway_status={"ready": True},
        )


def fake_pod(
    *,
    phase: str,
    ready: bool = False,
    message: str = "",
) -> FakeKubernetesModel:
    conditions = [
        FakeKubernetesModel(type="Ready", status="True" if ready else "False")
    ]
    return FakeKubernetesModel(
        status=FakeKubernetesModel(
            phase=phase,
            conditions=conditions,
            message=message,
            reason="",
            container_statuses=[],
        )
    )


def fake_deployment(*, replicas: int = 1, ready_replicas: int = 0) -> FakeKubernetesModel:
    return FakeKubernetesModel(
        spec=FakeKubernetesModel(replicas=replicas),
        status=FakeKubernetesModel(ready_replicas=ready_replicas),
    )


def supergateway_stdio_arg(manifest) -> str:
    args = manifest.pod.spec.containers[0].args
    return args[args.index("--stdio") + 1]


def test_kubernetes_client_factory_prefers_in_cluster_config() -> None:
    config = FakeKubernetesConfig()
    factory = KubernetesClientFactory(settings=FakeSettings(), config_module=config)

    assert factory.load_config() == "in_cluster"
    assert config.loaded == [("in_cluster", {})]


def test_kubernetes_client_factory_falls_back_to_kubeconfig() -> None:
    config = FakeKubernetesConfig(in_cluster_error=RuntimeError("not in cluster"))
    factory = KubernetesClientFactory(settings=FakeSettings(), config_module=config)

    assert factory.load_config() == "kubeconfig"
    assert config.loaded == [
        ("in_cluster", {}),
        ("kubeconfig", {"config_file": "/tmp/kubeconfig", "context": "local"}),
    ]


def test_kubernetes_client_factory_can_disable_kubeconfig_fallback() -> None:
    config = FakeKubernetesConfig(in_cluster_error=RuntimeError("not in cluster"))
    settings = type(
        "Settings",
        (),
        {
            "mcp_runtime_kubernetes_allow_kubeconfig": False,
            "mcp_runtime_kubernetes_kubeconfig_path": "",
            "mcp_runtime_kubernetes_context": "",
        },
    )()
    factory = KubernetesClientFactory(settings=settings, config_module=config)

    with pytest.raises(KubernetesConfigError, match="kubeconfig fallback is disabled"):
        factory.load_config()


def test_kubernetes_runtime_names_are_deterministic_and_safe() -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()

    names = runtime_object_names(
        runtime_session_id=runtime_session_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        prefix="Wardn Runtime",
    )

    assert names == runtime_object_names(
        runtime_session_id=runtime_session_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        prefix="Wardn Runtime",
    )
    assert names.namespace.startswith("wardn-runtime-org-")
    assert "-ws-" in names.namespace
    assert names.pod_name.startswith("mcp-")
    assert names.service_name.endswith("-svc")
    assert names.secret_name.endswith("-secret")
    assert all(len(value) <= 63 for value in names.__dict__.values())


def test_kubernetes_runtime_names_use_server_and_config_instance() -> None:
    workspace_id = uuid.uuid4()

    names = runtime_object_names(
        server_name="io.github.example/weather",
        config_name="prod",
        organization_id=None,
        workspace_id=workspace_id,
        prefix="wardn",
    )

    assert names.pod_name == "io-github-example-weather-prod"
    assert names.service_name == "io-github-example-weather-prod-svc"
    assert names.secret_name == "io-github-example-weather-prod-secret"


def test_kubernetes_runtime_names_default_config_instance() -> None:
    assert runtime_object_base_name(
        server_name="io.github.example/weather",
        config_name="",
    ) == "io-github-example-weather-default"


def test_kubernetes_namespace_supports_workspace_without_org() -> None:
    workspace_id = uuid.uuid4()

    assert runtime_namespace_name(
        organization_id=None,
        workspace_id=workspace_id,
        prefix="wardn",
    ).startswith("wardn-ws-")


def test_safe_kubernetes_name_adds_hash_when_truncated() -> None:
    value = "A" * 120

    safe_name = safe_kubernetes_name(value)

    assert len(safe_name) == 63
    assert safe_name.startswith("a")
    assert safe_name != "a" * 63


def test_runtime_labels_do_not_include_secret_values() -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()
    secret = "super-secret-token"

    labels = runtime_labels(
        organization_id=organization_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        runtime_id="runtime-fingerprint",
        runtime_session_id=runtime_session_id,
        server_name=f"io.github.example/weather/{secret}",
        server_version="1.0.0+prod",
    )

    assert labels[KUBERNETES_LABEL_APP_NAME] == "wardn-mcp-runtime"
    assert labels[WARDN_LABEL_WORKSPACE_ID] == str(workspace_id)
    assert labels[WARDN_LABEL_INSTALLATION_ID] == str(installation_id)
    assert labels[WARDN_LABEL_RUNTIME_ID].startswith("runtime-")
    assert labels[WARDN_LABEL_RUNTIME_SESSION_ID] == str(runtime_session_id)
    assert secret not in labels[WARDN_LABEL_SERVER_NAME]
    assert secret not in repr(labels)


def test_runtime_object_names_are_stable_for_same_config_fingerprint() -> None:
    workspace_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    first_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="same-runtime-config",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    first_session.id = uuid.uuid4()
    second_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="same-runtime-config",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    second_session.id = uuid.uuid4()

    assert runtime_object_identity(first_session) == "same-runtime-config"
    assert runtime_object_names_for_session(
        first_session,
        settings=FakeSettings(),
    ) == runtime_object_names_for_session(
        second_session,
        settings=FakeSettings(),
    )


def test_runtime_manifest_uses_config_instance_for_deployment_name(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        config_name="prod",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert runtime_installation_identity(installation) == "io.github.example/weather:prod"
    assert manifest.names.pod_name == "io-github-example-weather-prod"
    assert manifest.deployment.metadata.name == "io-github-example-weather-prod"


def test_runtime_manifest_does_not_create_ingress_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.ingress is None


def test_runtime_manifest_hardens_runtime_pod_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "npm",
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "package": {"identifier": "weather-mcp", "version": "1.0.0"},
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.namespace.metadata.labels["pod-security.kubernetes.io/enforce"] == "restricted"
    assert manifest.pod.spec.automount_service_account_token is False
    assert manifest.pod.spec.enable_service_links is False
    assert manifest.pod.spec.host_ipc is False
    assert manifest.pod.spec.host_network is False
    assert manifest.pod.spec.host_pid is False
    assert manifest.pod.spec.runtime_class_name is None
    assert manifest.pod.spec.security_context.run_as_non_root is True
    assert manifest.pod.spec.security_context.run_as_user == 1000
    assert manifest.pod.spec.security_context.run_as_group == 1000
    assert manifest.pod.spec.security_context.fs_group == 1000
    assert manifest.pod.spec.security_context.fs_group_change_policy == "OnRootMismatch"
    assert manifest.pod.spec.security_context.seccomp_profile.type == "RuntimeDefault"

    container = manifest.pod.spec.containers[0]
    assert container.security_context.allow_privilege_escalation is False
    assert container.security_context.privileged is False
    assert container.security_context.read_only_root_filesystem is True
    assert container.security_context.capabilities.drop == ["ALL"]
    assert container.security_context.seccomp_profile.type == "RuntimeDefault"
    assert {mount.mount_path for mount in container.volume_mounts} >= {
        "/tmp",
        "/opt/wardn/npm-package",
    }
    assert {volume.name for volume in manifest.pod.spec.volumes} >= {
        "runtime-tmp",
        "npm-package",
    }
    assert {env.name: env.value for env in container.env if getattr(env, "value", None)} == {
        "HOME": "/tmp/wardn-home",
        "NPM_CONFIG_CACHE": "/tmp/wardn-cache/npm",
        "UV_CACHE_DIR": "/tmp/wardn-cache/uv",
        "XDG_CACHE_HOME": "/tmp/wardn-cache",
    }

    init_container = manifest.pod.spec.init_containers[0]
    assert init_container.security_context.allow_privilege_escalation is False
    assert init_container.security_context.capabilities.drop == ["ALL"]
    assert {mount.mount_path for mount in init_container.volume_mounts} == {
        "/opt/wardn/npm-package",
        "/tmp",
    }


def test_runtime_manifest_generates_strict_network_policies(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert [policy.spec.policy_types for policy in manifest.network_policies] == [
        ["Ingress", "Egress"],
        ["Ingress"],
        ["Egress"],
        ["Egress"],
    ]
    default_deny, ingress, dns_egress, public_egress = manifest.network_policies
    assert default_deny.spec.ingress == []
    assert default_deny.spec.egress == []

    ingress_rule = ingress.spec.ingress[0]
    assert ingress.spec.pod_selector.match_labels[WARDN_LABEL_RUNTIME_ID].startswith("runtime-")
    assert ingress_rule._from[0].namespace_selector.match_labels == {
        "kubernetes.io/metadata.name": "wardn"
    }
    assert ingress_rule._from[0].pod_selector.match_labels == {
        "app.kubernetes.io/part-of": "wardn-ai"
    }
    assert ingress_rule.ports[0].protocol == "TCP"
    assert ingress_rule.ports[0].port == 8000

    dns_rule = dns_egress.spec.egress[0]
    assert dns_rule.to[0].namespace_selector.match_labels == {
        "kubernetes.io/metadata.name": "kube-system"
    }
    assert dns_rule.to[0].pod_selector.match_labels == {"k8s-app": "kube-dns"}
    assert {(port.protocol, port.port) for port in dns_rule.ports} == {
        ("UDP", 53),
        ("TCP", 53),
    }

    public_rule = public_egress.spec.egress[0]
    assert public_rule.to[0].ip_block.cidr == "0.0.0.0/0"
    assert "10.0.0.0/8" in public_rule.to[0].ip_block._except
    assert "192.168.0.0/16" in public_rule.to[0].ip_block._except
    assert [(port.protocol, port.port) for port in public_rule.ports] == [
        ("TCP", 80),
        ("TCP", 443),
    ]


def test_runtime_manifest_can_create_ingress_for_traefik_and_external_dns(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        config_name="prod",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=IngressSettings(),
        client_module=FakeKubernetesClient,
    )

    host = "io-github-example-weather-prod.mcp.example.com"
    ingress = manifest.ingress
    assert ingress is not None
    assert ingress.metadata.name == manifest.names.ingress_name
    assert ingress.metadata.annotations == {
        "kubernetes.io/ingress.class": "traefik",
        "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
        "traefik.ingress.kubernetes.io/router.tls": "true",
        "external-dns.alpha.kubernetes.io/hostname": host,
        "example.com/owner": "wardn",
    }
    assert ingress.spec.ingress_class_name == "traefik"
    assert ingress.spec.tls[0].hosts == [host]
    assert ingress.spec.tls[0].secret_name == "mcp-tls"
    assert ingress.spec.rules[0].host == host
    path = ingress.spec.rules[0].http.paths[0]
    assert path.path == "/"
    assert path.backend.service.name == manifest.names.service_name
    assert path.backend.service.port.number == 8000


def test_runtime_manifest_requires_base_domain_when_ingress_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )

    class MissingDomainIngressSettings(FakeSettings):
        mcp_runtime_kubernetes_ingress_enabled = True

    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    with pytest.raises(KubernetesIngressError, match="base domain is required"):
        build_runtime_manifests(
            installation,
            runtime_session,
            settings=MissingDomainIngressSettings(),
            client_module=FakeKubernetesClient,
        )


def test_kubernetes_provider_runtime_spec_uses_streamable_http_transport(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()

    runtime_spec = KubernetesRuntimeProvider().runtime_spec(installation)

    assert runtime_spec.provider_name == RUNTIME_PROVIDER_KUBERNETES
    assert runtime_spec.transport == RUNTIME_TRANSPORT_STREAMABLE_HTTP
    assert runtime_spec.command == "node"


def test_kubernetes_runtime_manifest_keeps_secret_values_only_in_secret(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    secret_value = "super-secret-token"
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp", "--stdio"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
        secret_references={
            "environment": {"WEATHER_TOKEN": secret_value},
            "headers": {"Authorization": f"Bearer {secret_value}"},
        },
    )
    installation.id = installation_id
    runtime_session = MCPRuntimeSession(
        organization_id=organization_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = runtime_session_id

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.secret.string_data["WEATHER_TOKEN"] == secret_value
    assert secret_value in manifest.secret.string_data[WARDN_CUSTOM_HEADERS_ENV]
    assert secret_value not in repr(manifest.labels)
    assert secret_value not in repr(manifest.namespace)
    assert secret_value not in repr(manifest.pod)
    assert secret_value not in repr(manifest.service)
    assert secret_value not in repr(manifest.network_policies)


def test_kubernetes_runtime_manifest_rolls_pod_when_secret_values_change(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    def build_manifest(secret_value: str):
        installation = MCPServerInstallation(
            workspace_id=workspace_id,
            server_name="io.github.example/weather",
            installed_version="1.0.0",
            status="enabled",
            install_type="npm",
            install_path=str(tmp_path),
            runtime_config={
                "kind": RUNTIME_KIND_PACKAGE,
                "command": "node",
                "args": ["weather-mcp"],
                "cwd": str(tmp_path),
                "transport": {"type": RUNTIME_TRANSPORT_STDIO},
            },
            secret_references={"environment": {"WEATHER_TOKEN": secret_value}},
        )
        installation.id = installation_id
        return build_runtime_manifests(
            installation,
            runtime_session,
            settings=FakeSettings(),
            client_module=FakeKubernetesClient,
        )

    first = build_manifest("first-secret")
    second = build_manifest("second-secret")
    first_annotations = first.pod.metadata.annotations
    second_annotations = second.pod.metadata.annotations

    assert (
        first_annotations[WARDN_RUNTIME_CONFIG_CHECKSUM_ANNOTATION]
        == "runtime-fingerprint"
    )
    assert first_annotations[WARDN_RUNTIME_SECRET_CHECKSUM_ANNOTATION]
    assert first_annotations[WARDN_RUNTIME_SECRET_CHECKSUM_ANNOTATION] != (
        second_annotations[WARDN_RUNTIME_SECRET_CHECKSUM_ANNOTATION]
    )
    assert "first-secret" not in repr(first.pod)
    assert "second-secret" not in repr(second.pod)


def test_kubernetes_runtime_manifest_uses_secret_refs_for_gateway_env(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
        secret_references={"environment": {"WEATHER_TOKEN": "secret"}},
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )
    container = manifest.pod.spec.containers[0]
    env_by_name = {env.name: env for env in container.env}

    assert set(env_by_name) == {
        "HOME",
        "NPM_CONFIG_CACHE",
        "UV_CACHE_DIR",
        "WEATHER_TOKEN",
        "XDG_CACHE_HOME",
    }
    assert manifest.secret.string_data == {"WEATHER_TOKEN": "secret"}
    assert container.args == [
        "--stdio",
        f"sh -lc 'cd {tmp_path} && node weather-mcp'",
        "--outputTransport",
        "streamableHttp",
        "--port",
        "8000",
        "--streamableHttpPath",
        "/mcp",
        "--healthEndpoint",
        "/healthz",
    ]
    assert env_by_name["HOME"].value == "/tmp/wardn-home"
    assert env_by_name["NPM_CONFIG_CACHE"].value == "/tmp/wardn-cache/npm"
    assert env_by_name["UV_CACHE_DIR"].value == "/tmp/wardn-cache/uv"
    assert env_by_name["XDG_CACHE_HOME"].value == "/tmp/wardn-cache"
    assert getattr(env_by_name["WEATHER_TOKEN"], "value", None) is None
    assert env_by_name["WEATHER_TOKEN"].value_from.secret_key_ref.name == manifest.names.secret_name
    assert env_by_name["WEATHER_TOKEN"].value_from.secret_key_ref.key == "WEATHER_TOKEN"


def test_kubernetes_runtime_manifest_adds_gateway_health_probes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )
    container = manifest.pod.spec.containers[0]

    assert container.readiness_probe.http_get.path == "/healthz"
    assert container.readiness_probe.http_get.port == "http"
    assert container.readiness_probe.initial_delay_seconds == 2
    assert container.readiness_probe.period_seconds == 10
    assert container.readiness_probe.timeout_seconds == 3
    assert container.readiness_probe.failure_threshold == 3
    assert container.liveness_probe.http_get.path == "/healthz"
    assert container.liveness_probe.initial_delay_seconds == 30
    assert container.startup_probe.http_get.path == "/healthz"
    assert container.startup_probe.failure_threshold == 180


def test_kubernetes_runtime_manifest_can_disable_gateway_health_probes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=DisabledProbeSettings(),
        client_module=FakeKubernetesClient,
    )
    container = manifest.pod.spec.containers[0]

    assert not hasattr(container, "readiness_probe")
    assert not hasattr(container, "liveness_probe")
    assert not hasattr(container, "startup_probe")


def test_kubernetes_runtime_manifest_rewrites_uvx_host_paths(
    tmp_path,
    monkeypatch,
) -> None:
    uvx_path = tmp_path / "uvx"
    uvx_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(uvx_path),
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/grafana",
        installed_version="1.0.0",
        status="enabled",
        install_type="uvx",
        install_path=str(tmp_path / "install"),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "uvx",
            "command": str(uvx_path),
            "args": ["mcp-grafana"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == "uvx mcp-grafana"
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"


def test_kubernetes_runtime_manifest_installs_npm_package_in_init_container(
    tmp_path,
    monkeypatch,
) -> None:
    node_path = tmp_path / "node"
    node_path.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_path = tmp_path / "node_modules" / ".bin" / "weather-mcp"
    bin_path.parent.mkdir(parents=True)
    bin_path.write_text("console.log('ok');\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(node_path) if command == "node" else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "npm",
            "command": "node",
            "args": [str(bin_path), "--stdio"],
            "cwd": str(tmp_path),
            "package": {"identifier": "weather-mcp", "version": "1.2.3"},
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == (
        "/opt/wardn/npm-package/node_modules/.bin/weather-mcp --stdio"
    )
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"
    assert manifest.pod.spec.containers[0].resources.requests == {
        "cpu": "100m",
        "memory": "256Mi",
    }
    assert manifest.pod.spec.containers[0].resources.limits == {
        "cpu": "1",
        "memory": "1Gi",
    }
    assert {volume.name for volume in manifest.pod.spec.volumes} >= {
        "npm-package",
        "runtime-tmp",
    }
    assert {mount.mount_path for mount in manifest.pod.spec.containers[0].volume_mounts} >= {
        "/opt/wardn/npm-package",
        "/tmp",
    }
    init_container = manifest.pod.spec.init_containers[0]
    assert init_container.name == "install-npm-package"
    assert init_container.image == "registry.example/supergateway:test"
    assert init_container.command == ["sh", "-lc"]
    assert init_container.args == [
        (
            "npm install --omit=dev --no-audit --no-fund --prefix "
            "/opt/wardn/npm-package weather-mcp@1.2.3"
        )
    ]
    assert init_container.resources.requests == {"cpu": "100m", "memory": "256Mi"}
    assert init_container.resources.limits == {"cpu": "1", "memory": "1Gi"}


def test_kubernetes_runtime_manifest_runs_oci_image_directly(
    tmp_path,
) -> None:
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/grafana",
        installed_version="1.0.0",
        status="enabled",
        install_type="oci",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "oci",
            "command": "/usr/bin/docker",
            "args": [
                "run",
                "--rm",
                "-i",
                "-e",
                "GRAFANA_URL",
                "docker.io/example/grafana-mcp:1.0.0",
                "--disable-write",
                "-t",
                "stdio",
            ],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
        secret_references={"environment": {"GRAFANA_URL": "https://grafana.example.com"}},
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    container = manifest.pod.spec.containers[0]
    assert container.name == "mcp-server"
    assert container.image == "docker.io/example/grafana-mcp:1.0.0"
    assert container.args == [
        "--disable-write",
        "-t",
        "streamable-http",
        "-address",
        "0.0.0.0:8000",
        "-endpoint-path",
        "/mcp",
    ]
    assert {env.name for env in container.env} == {
        "GRAFANA_URL",
        "HOME",
        "NPM_CONFIG_CACHE",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    }
    assert manifest.pod.spec.init_containers is None
    assert manifest.health_path is None
    assert not hasattr(container, "readiness_probe")


def test_kubernetes_runtime_manifest_uses_oci_native_http_command(
    tmp_path,
) -> None:
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.github/github-mcp-server",
        installed_version="1.5.0",
        status="enabled",
        install_type="oci",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "oci",
            "command": "/usr/bin/docker",
            "containerImage": "ghcr.io/github/github-mcp-server",
            "containerArgs": [],
            "args": ["run", "--rm", "-i", "ghcr.io/github/github-mcp-server"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
            "package": {
                "registryType": "oci",
                "identifier": "ghcr.io/github/github-mcp-server",
                "packageArguments": [
                    {"name": "http command", "value": "http", "includeInLaunch": False},
                    {"flag": "--listen-host", "includeInLaunch": False},
                    {"flag": "--port", "default": "8082", "includeInLaunch": False},
                ],
            },
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    container = manifest.pod.spec.containers[0]
    assert container.image == "ghcr.io/github/github-mcp-server"
    assert container.args == ["http", "--listen-host", "0.0.0.0", "--port", "8000"]
    assert manifest.health_path is None


def test_kubernetes_runtime_request_headers_use_github_token() -> None:
    installation = MCPServerInstallation(
        server_name="io.github.github/github-mcp-server",
        installed_version="1.5.0",
        status="enabled",
        install_type="oci",
        secret_references={"environment": {"GITHUB_PERSONAL_ACCESS_TOKEN": "token"}},
    )

    assert runtime_request_headers(installation) == {"Authorization": "Bearer token"}


def test_kubernetes_runtime_request_headers_preserve_explicit_authorization() -> None:
    installation = MCPServerInstallation(
        server_name="io.github.github/github-mcp-server",
        installed_version="1.5.0",
        status="enabled",
        install_type="oci",
        secret_references={
            "headers": {"Authorization": "Bearer explicit"},
            "environment": {"GITHUB_PERSONAL_ACCESS_TOKEN": "token"},
        },
    )

    assert runtime_request_headers(installation) == {"Authorization": "Bearer explicit"}


def test_kubernetes_runtime_manifest_mounts_runtime_files(
    tmp_path,
) -> None:
    local_ca_path = str(tmp_path / "runtime-files" / "GRAFANA_CLI_TLS_CA_FILE")
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/grafana",
        installed_version="1.0.0",
        status="enabled",
        install_type="oci",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "oci",
            "args": [
                "run",
                "--rm",
                "docker.io/example/grafana-mcp:1.0.0",
                "--tls-ca-file",
                local_ca_path,
            ],
            "fileMounts": [
                {
                    "name": "GRAFANA_CLI_TLS_CA_FILE",
                    "key": "GRAFANA_CLI_TLS_CA_FILE",
                    "path": local_ca_path,
                    "mountPath": "/opt/wardn/runtime-files/GRAFANA_CLI_TLS_CA_FILE",
                }
            ],
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
        secret_references={
            "environment": {"GRAFANA_URL": "https://grafana.example.com"},
            "files": {
                "GRAFANA_CLI_TLS_CA_FILE": {
                    "key": "GRAFANA_CLI_TLS_CA_FILE",
                    "path": local_ca_path,
                    "mountPath": "/opt/wardn/runtime-files/GRAFANA_CLI_TLS_CA_FILE",
                    "content": "ca",
                }
            },
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    container = manifest.pod.spec.containers[0]
    assert container.args == [
        "--tls-ca-file",
        "/opt/wardn/runtime-files/GRAFANA_CLI_TLS_CA_FILE",
        "-t",
        "streamable-http",
        "-address",
        "0.0.0.0:8000",
        "-endpoint-path",
        "/mcp",
    ]
    assert {env.name for env in container.env} == {
        "GRAFANA_URL",
        "HOME",
        "NPM_CONFIG_CACHE",
        "UV_CACHE_DIR",
        "XDG_CACHE_HOME",
    }
    assert manifest.secret.string_data == {
        "GRAFANA_URL": "https://grafana.example.com",
        "runtime-file-grafana-cli-tls-ca-file": "ca",
    }
    assert manifest.secret_env_keys == ["GRAFANA_URL"]
    volume = next(
        volume for volume in manifest.pod.spec.volumes if volume.name == "runtime-files"
    )
    assert volume.name == "runtime-files"
    assert volume.secret.secret_name == manifest.names.secret_name
    assert volume.secret.items[0].key == "runtime-file-grafana-cli-tls-ca-file"
    assert volume.secret.items[0].path == "GRAFANA_CLI_TLS_CA_FILE"
    mount = next(
        mount
        for mount in container.volume_mounts
        if mount.mount_path == "/opt/wardn/runtime-files"
    )
    assert mount.read_only is True


def test_kubernetes_runtime_manifest_preserves_oci_http_port_args(
    tmp_path,
) -> None:
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.containers/kubernetes-mcp-server",
        installed_version="0.0.63",
        status="enabled",
        install_type="oci",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "oci",
            "args": [
                "run",
                "--rm",
                "ghcr.io/containers/kubernetes-mcp-server:v0.0.63",
                "--port",
                "8000",
                "--stateless",
            ],
            "transport": {"type": RUNTIME_TRANSPORT_STREAMABLE_HTTP},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.pod.spec.containers[0].args == [
        "--port",
        "8000",
        "--stateless",
    ]


def test_kubernetes_runtime_manifest_rewrites_pypi_host_paths_to_uvx(
    tmp_path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(python_path) if command == str(python_path) else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/openstack",
        installed_version="1.0.0",
        status="enabled",
        install_type="pypi",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "pypi",
            "command": str(python_path),
            "args": ["-m", "openstackmcp_server", "--stdio"],
            "cwd": str(tmp_path),
            "package": {"identifier": "openstackmcp-server", "version": "latest"},
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == (
        "uvx --from openstackmcp-server python -m openstackmcp_server --stdio"
    )
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"


def test_kubernetes_runtime_manifest_uses_declared_pypi_python_module(
    tmp_path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(python_path) if command == str(python_path) else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.crypto-ninja/github-mcp-server",
        installed_version="1.0.0",
        status="enabled",
        install_type="pypi",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "pypi",
            "command": str(python_path),
            "args": ["-m", "github_mcp"],
            "cwd": str(tmp_path),
            "package": {
                "identifier": "github-mcp-server",
                "version": "2.5.7",
                "transport": {
                    "type": RUNTIME_TRANSPORT_STDIO,
                    "command": "python3",
                    "args": ["-m", "github_mcp"],
                },
            },
            "transport": {
                "type": RUNTIME_TRANSPORT_STDIO,
                "command": "python3",
                "args": ["-m", "github_mcp"],
            },
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == (
        "uvx --from github-mcp-server==2.5.7 python -m github_mcp"
    )
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"


def test_kubernetes_runtime_manifest_uses_package_gateway_image_override(
    tmp_path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(python_path) if command == str(python_path) else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/custom",
        installed_version="1.0.0",
        status="enabled",
        install_type="pypi",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "pypi",
            "command": str(python_path),
            "args": ["-m", "example_mcp"],
            "cwd": str(tmp_path),
            "package": {
                "identifier": "example-mcp",
                "version": "1.0.0",
                "gatewayImage": "registry.example/custom-gateway:1.0.0",
            },
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.pod.spec.containers[0].image == "registry.example/custom-gateway:1.0.0"


def test_kubernetes_runtime_manifest_uses_pypi_declared_uvx_command(
    tmp_path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(python_path) if command == str(python_path) else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.acamolese/google-search-console-mcp",
        installed_version="1.0.1",
        status="enabled",
        install_type="pypi",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "pypi",
            "command": str(python_path),
            "args": ["-m", "mcp_google_search_console"],
            "cwd": str(tmp_path),
            "package": {
                "identifier": "mcp-google-search-console",
                "version": "2.0.2",
                "transport": {
                    "type": RUNTIME_TRANSPORT_STDIO,
                    "command": "uvx",
                    "args": ["mcp-google-search-console"],
                },
            },
            "transport": {
                "type": RUNTIME_TRANSPORT_STDIO,
                "command": "uvx",
                "args": ["mcp-google-search-console"],
            },
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == (
        "uvx --from mcp-google-search-console==2.0.2 mcp-google-search-console"
    )
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"


def test_kubernetes_runtime_manifest_deduplicates_installed_pypi_transport_args(
    tmp_path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(python_path) if command == str(python_path) else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.AIops-tools/k8s-aiops",
        installed_version="0.2.0",
        status="enabled",
        install_type="pypi",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "pypi",
            "command": str(python_path),
            "args": ["mcp"],
            "cwd": str(tmp_path),
            "package": {
                "identifier": "k8s-aiops",
                "version": "0.2.0",
                "transport": {
                    "type": RUNTIME_TRANSPORT_STDIO,
                    "command": "k8s-aiops",
                    "args": ["mcp"],
                },
            },
            "transport": {
                "type": RUNTIME_TRANSPORT_STDIO,
                "command": "k8s-aiops",
                "args": ["mcp"],
            },
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == (
        "uvx --from k8s-aiops==0.2.0 k8s-aiops mcp"
    )


def test_kubernetes_runtime_manifest_adds_pypi_runtime_dependencies(
    tmp_path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: str(python_path) if command == str(python_path) else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.acamolese/google-search-console-mcp",
        installed_version="1.0.1",
        status="enabled",
        install_type="pypi",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "pypi",
            "command": str(python_path),
            "args": ["-m", "mcp_google_search_console"],
            "cwd": str(tmp_path),
            "package": {
                "identifier": "mcp-google-search-console",
                "version": "2.0.2",
                "pythonDependencies": ["mcp<2"],
                "transport": {
                    "type": RUNTIME_TRANSPORT_STDIO,
                    "command": "uvx",
                    "args": ["mcp-google-search-console"],
                },
            },
            "transport": {
                "type": RUNTIME_TRANSPORT_STDIO,
                "command": "uvx",
                "args": ["mcp-google-search-console"],
            },
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert supergateway_stdio_arg(manifest) == (
        "uvx --from mcp-google-search-console==2.0.2 --with 'mcp<2' "
        "mcp-google-search-console"
    )
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"


def test_kubernetes_runtime_manifest_uses_managed_gateway_image_for_deno(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/deno" if command == "deno" else None,
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/deno",
        installed_version="1.0.0",
        status="enabled",
        install_type="deno",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "registryType": "deno",
            "command": "deno",
            "args": ["run", "-A", "jsr:@example/mcp-server"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert "deno run -A jsr:@example/mcp-server" in supergateway_stdio_arg(manifest)
    assert manifest.pod.spec.containers[0].image == "registry.example/supergateway:test"


def test_kubernetes_runtime_manifest_service_selects_pod_labels(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.service.spec.type == "ClusterIP"
    assert manifest.service.spec.ports[0].port == 8000
    assert manifest.service.spec.ports[0].target_port == 8000
    assert all(
        manifest.pod.metadata.labels[key] == value
        for key, value in manifest.service.spec.selector.items()
    )
    assert WARDN_LABEL_RUNTIME_SESSION_ID not in manifest.pod.metadata.labels
    assert WARDN_LABEL_RUNTIME_SESSION_ID in manifest.deployment.metadata.labels
    assert manifest.ingress is None


def test_kubernetes_runtime_manifest_binds_existing_image_pull_secret(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=ImagePullSecretSettings(),
        client_module=FakeKubernetesClient,
    )

    assert [secret.name for secret in manifest.pod.spec.image_pull_secrets] == [
        "registry-credentials",
    ]


def test_kubernetes_runtime_manifest_rejects_invalid_image_pull_secret_names(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    settings = type(
        "Settings",
        (FakeSettings,),
        {
            "mcp_runtime_kubernetes_image_pull_secret_name": "Registry_Credentials",
        },
    )()
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    with pytest.raises(KubernetesImagePullSecretError, match="DNS subdomain"):
        build_runtime_manifests(
            installation,
            runtime_session,
            settings=settings,
            client_module=FakeKubernetesClient,
        )


def test_kubernetes_runtime_manifest_includes_custom_namespace_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=CustomNamespaceMetadataSettings(),
        client_module=FakeKubernetesClient,
    )

    assert manifest.namespace.metadata.labels["billing.example.com/team"] == "runtime"
    assert manifest.namespace.metadata.labels["environment"] == "dev"
    assert manifest.namespace.metadata.labels["wardn.ai/runtime-session-id"] == str(
        runtime_session.id
    )
    assert manifest.namespace.metadata.annotations == {
        "owner.example.com/team": "platform",
        "notes": "runtime namespace",
    }


def test_kubernetes_runtime_manifest_rejects_reserved_custom_namespace_labels(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    settings = type(
        "Settings",
        (FakeSettings,),
        {
            "mcp_runtime_kubernetes_namespace_labels_json": '{"wardn.ai/scope":"bad"}',
        },
    )()
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    with pytest.raises(KubernetesMetadataError, match="reserved"):
        build_runtime_manifests(
            installation,
            runtime_session,
            settings=settings,
            client_module=FakeKubernetesClient,
        )


def test_kubernetes_runtime_manifest_rejects_invalid_custom_namespace_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    settings = type(
        "Settings",
        (FakeSettings,),
        {
            "mcp_runtime_kubernetes_namespace_annotations_json": '{"bad key":"value"}',
        },
    )()
    installation = MCPServerInstallation(
        workspace_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()

    with pytest.raises(KubernetesMetadataError, match="invalid name"):
        build_runtime_manifests(
            installation,
            runtime_session,
            settings=settings,
            client_module=FakeKubernetesClient,
        )


def test_kubernetes_reconciler_creates_runtime_objects(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )
    core_v1 = FakeCoreV1Api()
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
    )

    result = reconciler.reconcile(manifest)

    assert result.endpoint_url == (
        f"http://{manifest.names.service_name}.{manifest.names.namespace}"
        ".svc.cluster.local:8000/mcp"
    )
    network_policy_calls = [
        ("create_namespaced_network_policy", policy.metadata.name, manifest.names.namespace)
        for policy in manifest.network_policies
    ]
    assert core_v1.calls == [
        ("read_namespace", manifest.names.namespace, ""),
        ("create_namespace", manifest.names.namespace, ""),
        *network_policy_calls,
        ("create_namespaced_secret", manifest.names.secret_name, manifest.names.namespace),
        ("create_namespaced_deployment", manifest.names.pod_name, manifest.names.namespace),
        ("create_namespaced_service", manifest.names.service_name, manifest.names.namespace),
    ]


def test_kubernetes_reconciler_creates_ingress_when_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        config_name="prod",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    settings = IngressSettings()
    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=settings,
        client_module=FakeKubernetesClient,
    )
    core_v1 = FakeCoreV1Api()
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=settings,
    )

    result = reconciler.reconcile(manifest)

    assert result.endpoint_url == "https://io-github-example-weather-prod.mcp.example.com/mcp"
    network_policy_calls = [
        ("create_namespaced_network_policy", policy.metadata.name, manifest.names.namespace)
        for policy in manifest.network_policies
    ]
    assert core_v1.calls == [
        ("read_namespace", manifest.names.namespace, ""),
        ("create_namespace", manifest.names.namespace, ""),
        *network_policy_calls,
        ("create_namespaced_secret", manifest.names.secret_name, manifest.names.namespace),
        ("create_namespaced_deployment", manifest.names.pod_name, manifest.names.namespace),
        ("create_namespaced_service", manifest.names.service_name, manifest.names.namespace),
        ("create_namespaced_ingress", manifest.names.ingress_name, manifest.names.namespace),
    ]


def test_kubernetes_reconciler_replaces_secret_and_service_on_conflict(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )
    core_v1 = FakeCoreV1Api()
    core_v1.conflicts = {
        "create_namespace",
        "create_namespaced_network_policy",
        "create_namespaced_secret",
        "create_namespaced_deployment",
        "create_namespaced_service",
    }
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
    )

    reconciler.reconcile(manifest)

    for policy in manifest.network_policies:
        assert (
            "replace_namespaced_network_policy",
            policy.metadata.name,
            manifest.names.namespace,
        ) in core_v1.calls
    assert (
        "replace_namespaced_secret",
        manifest.names.secret_name,
        manifest.names.namespace,
    ) in core_v1.calls
    assert (
        "replace_namespaced_service",
        manifest.names.service_name,
        manifest.names.namespace,
    ) in core_v1.calls
    assert (
        "replace_namespaced_deployment",
        manifest.names.pod_name,
        manifest.names.namespace,
    ) in core_v1.calls


def test_kubernetes_reconciler_uses_existing_runtime_namespace(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )
    core_v1 = FakeCoreV1Api()
    core_v1.namespaces.add(manifest.names.namespace)
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
    )

    reconciler.reconcile(manifest)

    assert ("read_namespace", manifest.names.namespace, "") in core_v1.calls
    assert ("create_namespace", manifest.names.namespace, "") not in core_v1.calls
    assert (
        "create_namespaced_deployment",
        manifest.names.pod_name,
        manifest.names.namespace,
    ) in core_v1.calls


def test_kubernetes_reconciler_surfaces_api_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    manifest = build_runtime_manifests(
        installation,
        runtime_session,
        settings=FakeSettings(),
        client_module=FakeKubernetesClient,
    )
    core_v1 = FakeCoreV1Api()
    core_v1.errors["create_namespace"] = FakeApiException(403, "Forbidden", "no rbac")
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
    )

    with pytest.raises(KubernetesReconcileError, match="403 Forbidden no rbac"):
        reconciler.reconcile(manifest)


def test_kubernetes_reconciler_waits_for_ready_deployment() -> None:
    names = runtime_object_names(
        runtime_session_id=uuid.uuid4(),
        organization_id=None,
        workspace_id=uuid.uuid4(),
        prefix="wardn",
    )
    core_v1 = FakeCoreV1Api()
    core_v1.deployments.extend(
        [
            fake_deployment(replicas=1, ready_replicas=0),
            fake_deployment(replicas=1, ready_replicas=1),
        ]
    )
    ticks = iter([0, 1, 2])
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
        sleep=lambda seconds: None,
        monotonic=lambda: next(ticks),
    )

    deployment = reconciler.wait_for_deployment_ready(names, timeout_seconds=5)

    assert deployment.status.ready_replicas == 1
    assert [call[0] for call in core_v1.calls] == [
        "read_namespaced_deployment",
        "read_namespaced_deployment",
    ]


def test_kubernetes_reconciler_sets_api_request_timeout() -> None:
    seen_timeout = None

    def method(*, _request_timeout=None):
        nonlocal seen_timeout
        seen_timeout = _request_timeout
        return "ok"

    class TimeoutSettings(FakeSettings):
        mcp_runtime_kubernetes_api_timeout_seconds = 12

    reconciler = KubernetesRuntimeReconciler(
        core_v1=FakeCoreV1Api(),
        api_exception_class=FakeApiException,
        settings=TimeoutSettings(),
    )

    assert reconciler._call_api(method) == "ok"
    assert seen_timeout == (5, 12)


def test_kubernetes_reconciler_times_out_waiting_for_deployment() -> None:
    names = runtime_object_names(
        runtime_session_id=uuid.uuid4(),
        organization_id=None,
        workspace_id=uuid.uuid4(),
        prefix="wardn",
    )
    core_v1 = FakeCoreV1Api()
    core_v1.deployments.extend(
        [
            fake_deployment(replicas=1, ready_replicas=0),
            fake_deployment(replicas=1, ready_replicas=0),
        ]
    )
    ticks = iter([0, 1, 5])
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
        sleep=lambda seconds: None,
        monotonic=lambda: next(ticks),
    )

    with pytest.raises(KubernetesRuntimeNotReadyError, match="ready=0, desired=1"):
        reconciler.wait_for_deployment_ready(names, timeout_seconds=5)


def test_kubernetes_reconciler_waits_for_gateway_ready(monkeypatch) -> None:
    seen = []
    statuses = iter(
        [
            {"ready": False},
            {"ready": True, "status": 200, "body": "ok"},
        ]
    )

    def get_gateway_health(endpoint_url, *, verify_tls=True):
        seen.append((endpoint_url, verify_tls))
        return next(statuses)

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_reconciler.get_gateway_health",
        get_gateway_health,
    )
    ticks = iter([0, 1, 2])
    reconciler = KubernetesRuntimeReconciler(
        core_v1=FakeCoreV1Api(),
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
        sleep=lambda seconds: None,
        monotonic=lambda: next(ticks),
    )

    status = reconciler.wait_for_gateway_ready(
        "http://runtime.test:8000/mcp",
        timeout_seconds=5,
    )

    assert status == {"ready": True, "status": 200, "body": "ok"}
    assert seen == [
        ("http://runtime.test:8000/mcp", True),
        ("http://runtime.test:8000/mcp", True),
    ]


def test_kubernetes_reconciler_can_skip_ingress_tls_verification(monkeypatch) -> None:
    seen = []

    def get_gateway_health(endpoint_url, *, verify_tls=True):
        seen.append((endpoint_url, verify_tls))
        return {"ready": True, "status": 200, "body": "ok"}

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_reconciler.get_gateway_health",
        get_gateway_health,
    )
    ticks = iter([0, 1])
    reconciler = KubernetesRuntimeReconciler(
        core_v1=FakeCoreV1Api(),
        api_exception_class=FakeApiException,
        settings=IngressUnverifiedTlsSettings(),
        sleep=lambda seconds: None,
        monotonic=lambda: next(ticks),
    )

    status = reconciler.wait_for_gateway_ready(
        "https://runtime.example.test/mcp",
        timeout_seconds=5,
    )

    assert status == {"ready": True, "status": 200, "body": "ok"}
    assert seen == [("https://runtime.example.test/mcp", False)]


def test_kubernetes_provider_reconciles_and_lists_supergateway_runtime_tools(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_manifest_builder.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    core_v1 = FakeCoreV1Api()
    fake_reconciler = FakeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
    )
    provider = KubernetesRuntimeProvider(
        client_factory=FakeClientFactory(core_v1),
        reconciler_factory=lambda **kwargs: fake_reconciler,
    )
    seen = {}

    def list_tools(
        endpoint_url,
        headers,
        *,
        max_pages=100,
        verify_tls=True,
        outbound_policy=None,
    ):
        seen["endpoint_url"] = endpoint_url
        seen["headers"] = headers
        seen["max_pages"] = max_pages
        seen["verify_tls"] = verify_tls
        seen["outbound_policy"] = outbound_policy
        return [{"name": "health", "inputSchema": {"type": "object"}}]

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.mcp_client.list_tools",
        list_tools,
    )

    result = provider.list_tools(installation, runtime_session=runtime_session)

    assert result == [{"name": "health", "inputSchema": {"type": "object"}}]
    assert fake_reconciler.reconciled_manifest is not None
    expected_endpoint_url = runtime_service_endpoint_url(
        names=fake_reconciler.reconciled_manifest.names,
        gateway_port=FakeSettings.mcp_runtime_kubernetes_service_port,
    )
    assert seen["endpoint_url"] == expected_endpoint_url
    assert seen["headers"] == {}
    assert seen["max_pages"] == 100
    assert seen["verify_tls"] is True
    outbound_policy = seen["outbound_policy"]
    assert outbound_policy is not None
    assert outbound_policy.allow_http is True
    assert outbound_policy.allowed_ports == frozenset({8000})
    assert outbound_policy.private_host_allowlist == frozenset(
        {
            (
                f"{fake_reconciler.reconciled_manifest.names.service_name}."
                f"{fake_reconciler.reconciled_manifest.names.namespace}.svc.cluster.local"
            )
        }
    )
    assert runtime_session.endpoint_url == expected_endpoint_url


def test_kubernetes_provider_reconciles_and_invokes_supergateway_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_manifest_builder.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    core_v1 = FakeCoreV1Api()
    client_factory = FakeClientFactory(core_v1)
    fake_reconciler = FakeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
    )
    provider = KubernetesRuntimeProvider(
        client_factory=client_factory,
        reconciler_factory=lambda **kwargs: fake_reconciler,
    )
    seen = {}

    def call_tool(
        endpoint_url,
        headers,
        *,
        tool_name,
        arguments,
        cancel_event=None,
        cancel_reason="Tool call cancelled.",
        request_meta=None,
        progress_callback=None,
        verify_tls=True,
        outbound_policy=None,
    ):
        seen["endpoint_url"] = endpoint_url
        seen["headers"] = headers
        seen["tool_name"] = tool_name
        seen["arguments"] = arguments
        seen["request_meta"] = request_meta
        seen["verify_tls"] = verify_tls
        seen["outbound_policy"] = outbound_policy
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.mcp_client.call_tool",
        call_tool,
    )

    result = provider.call_tool(
        installation,
        tool_name="echo",
        arguments={"value": "ok"},
        runtime_session=runtime_session,
    )

    assert result == {"content": [{"type": "text", "text": "ok"}], "isError": False}
    assert fake_reconciler.reconciled_manifest is not None
    expected_endpoint_url = runtime_service_endpoint_url(
        names=fake_reconciler.reconciled_manifest.names,
        gateway_port=FakeSettings.mcp_runtime_kubernetes_service_port,
    )
    assert seen["endpoint_url"] == expected_endpoint_url
    assert seen["headers"] == {}
    assert seen["tool_name"] == "echo"
    assert seen["arguments"] == {"value": "ok"}
    assert seen["request_meta"] is None
    assert seen["verify_tls"] is True
    outbound_policy = seen["outbound_policy"]
    assert outbound_policy is not None
    assert outbound_policy.allow_http is True
    assert outbound_policy.allowed_ports == frozenset({8000})
    assert outbound_policy.private_host_allowlist == frozenset(
        {
            (
                f"{fake_reconciler.reconciled_manifest.names.service_name}."
                f"{fake_reconciler.reconciled_manifest.names.namespace}.svc.cluster.local"
            )
        }
    )
    assert client_factory.load_count == 1
    assert fake_reconciler.ready_endpoint_url == expected_endpoint_url
    assert runtime_session.namespace == fake_reconciler.reconciled_manifest.names.namespace
    assert runtime_session.pod_name == fake_reconciler.reconciled_manifest.names.pod_name
    assert runtime_session.endpoint_url == expected_endpoint_url

    second_result = provider.call_tool(
        installation,
        tool_name="echo",
        arguments={"value": "again"},
        runtime_session=runtime_session,
    )

    assert second_result["content"][0]["text"] == "ok"
    assert seen["arguments"] == {"value": "again"}


def test_kubernetes_provider_can_skip_tls_verification_for_ingress_tool_call(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.get_settings",
        lambda: IngressUnverifiedTlsSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_manifest_builder.get_settings",
        lambda: IngressUnverifiedTlsSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    core_v1 = FakeCoreV1Api()
    fake_reconciler = FakeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
    )
    provider = KubernetesRuntimeProvider(
        client_factory=FakeClientFactory(core_v1),
        reconciler_factory=lambda **kwargs: fake_reconciler,
    )
    seen = {}

    def call_tool(
        endpoint_url,
        headers,
        *,
        tool_name,
        arguments,
        cancel_event=None,
        cancel_reason="Tool call cancelled.",
        request_meta=None,
        progress_callback=None,
        verify_tls=True,
        outbound_policy=None,
    ):
        seen["request_meta"] = request_meta
        seen["verify_tls"] = verify_tls
        seen["outbound_policy"] = outbound_policy
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.mcp_client.call_tool",
        call_tool,
    )

    provider.call_tool(
        installation,
        tool_name="echo",
        arguments={"value": "ok"},
        runtime_session=runtime_session,
    )

    assert seen["verify_tls"] is False
    assert seen["outbound_policy"] is None


def test_kubernetes_provider_bubbles_supergateway_call_errors(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_manifest_builder.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    workspace_id = uuid.uuid4()
    installation = MCPServerInstallation(
        workspace_id=workspace_id,
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    provider = KubernetesRuntimeProvider(
        client_factory=FakeClientFactory(FakeCoreV1Api()),
        reconciler_factory=lambda **kwargs: FakeReconciler(**kwargs),
    )

    def call_tool(*args, **kwargs):
        raise RuntimeError("gateway failed")

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_provider.mcp_client.call_tool",
        call_tool,
    )

    with pytest.raises(RuntimeError, match="gateway failed"):
        provider.call_tool(
            installation,
            tool_name="echo",
            arguments={},
            runtime_session=runtime_session,
        )


def test_kubernetes_provider_does_not_load_client_without_runtime_session(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.provider.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": ["weather-mcp"],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    client_factory = FakeClientFactory(FakeCoreV1Api())
    provider = KubernetesRuntimeProvider(client_factory=client_factory)

    with pytest.raises(NotImplementedError, match="requires a runtime session"):
        provider.call_tool(
            installation,
            tool_name="echo",
            arguments={},
            runtime_session=None,
        )

    assert client_factory.load_count == 0


def test_kubernetes_provider_stop_runtime_scales_session_deployment_down(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_reconciler.get_settings",
        lambda: FakeSettings(),
    )
    workspace_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    names = runtime_object_names_for_session(runtime_session, settings=FakeSettings())
    core_v1 = FakeCoreV1Api()
    provider = KubernetesRuntimeProvider(client_factory=FakeClientFactory(core_v1))

    provider.stop_runtime(runtime_session)

    assert core_v1.calls == [
        ("patch_namespaced_deployment_scale", names.pod_name, names.namespace),
    ]


def test_kubernetes_provider_stop_runtime_can_delete_session_resources(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes_reconciler.get_settings",
        lambda: FakeSettings(),
    )
    workspace_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    runtime_session = MCPRuntimeSession(
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    names = runtime_object_names_for_session(runtime_session, settings=FakeSettings())
    core_v1 = FakeCoreV1Api()
    provider = KubernetesRuntimeProvider(client_factory=FakeClientFactory(core_v1))

    provider.stop_runtime(runtime_session, delete_resources=True)

    network_policy_calls = [
        ("delete_namespaced_network_policy", policy_name, names.namespace)
        for policy_name in runtime_network_policy_names(names)
    ]
    assert core_v1.calls == [
        ("delete_namespaced_ingress", names.ingress_name, names.namespace),
        *network_policy_calls,
        ("delete_namespaced_service", names.service_name, names.namespace),
        ("delete_namespaced_deployment", names.pod_name, names.namespace),
        ("delete_namespaced_secret", names.secret_name, names.namespace),
    ]


def test_kubernetes_provider_execution_fails_at_reconciliation_boundary() -> None:
    provider = KubernetesRuntimeProvider()
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        runtime_config={"kind": RUNTIME_KIND_PACKAGE},
    )

    with pytest.raises(NotImplementedError, match="requires a runtime session"):
        provider.list_tools(installation)


def test_kubernetes_provider_health_reports_ready_deployment() -> None:
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="weather-runtime",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    core_v1 = FakeCoreV1Api()
    core_v1.deployments.append(fake_deployment(replicas=1, ready_replicas=1))

    health = KubernetesRuntimeProvider(client_factory=FakeClientFactory(core_v1)).health(
        runtime_session
    )

    assert health.status == "ready"
    assert health.healthy is True
    assert health.ready is True
    assert health.details == {
        "namespace": "wardn-runtimes",
        "deploymentName": "weather-runtime",
        "desiredReplicas": 1,
        "readyReplicas": 1,
        "availableReplicas": 0,
        "updatedReplicas": 0,
    }


def test_kubernetes_provider_health_reports_not_ready_deployment() -> None:
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="weather-runtime",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )
    runtime_session.id = uuid.uuid4()
    core_v1 = FakeCoreV1Api()
    core_v1.deployments.append(fake_deployment(replicas=1, ready_replicas=0))

    health = KubernetesRuntimeProvider(client_factory=FakeClientFactory(core_v1)).health(
        runtime_session
    )

    assert health.status == "not_ready"
    assert health.healthy is False
    assert health.ready is False
    assert health.message == "Kubernetes runtime deployment is not ready; ready=0, desired=1."
    assert health.details["deploymentName"] == "weather-runtime"
