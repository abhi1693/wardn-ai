import uuid
from collections import deque

import pytest

from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.adapter_contract import (
    WARDN_RUNTIME_ARGS_JSON_ENV,
    WARDN_RUNTIME_COMMAND_ENV,
    WARDN_RUNTIME_CWD_ENV,
    WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV,
    WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV,
)
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
    WARDN_LABEL_RUNTIME_SESSION_ID,
    WARDN_LABEL_SERVER_NAME,
    WARDN_LABEL_WORKSPACE_ID,
    KubernetesClientFactory,
    KubernetesConfigError,
    KubernetesReconcileError,
    KubernetesReconcileResult,
    KubernetesRuntimeNotReadyError,
    KubernetesRuntimeProvider,
    KubernetesRuntimeReconciler,
    build_runtime_manifests,
    pod_is_ready,
    runtime_labels,
    runtime_namespace_name,
    runtime_object_names,
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
    mcp_runtime_kubernetes_adapter_image = "registry.example/wardn-adapter:test"
    mcp_runtime_kubernetes_service_port = 8000
    mcp_runtime_adapter_startup_timeout_seconds = 7
    mcp_runtime_adapter_request_timeout_seconds = 11


class FakeKubernetesModel:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeKubernetesClient:
    V1Container = FakeKubernetesModel
    V1ContainerPort = FakeKubernetesModel
    V1EnvVar = FakeKubernetesModel
    V1EnvVarSource = FakeKubernetesModel
    V1Namespace = FakeKubernetesModel
    V1ObjectMeta = FakeKubernetesModel
    V1Pod = FakeKubernetesModel
    V1PodSpec = FakeKubernetesModel
    V1Secret = FakeKubernetesModel
    V1SecretKeySelector = FakeKubernetesModel
    V1Service = FakeKubernetesModel
    V1ServicePort = FakeKubernetesModel
    V1ServiceSpec = FakeKubernetesModel


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
        self.pods: deque = deque()

    def _call(self, method: str, name: str = "", namespace: str = "") -> None:
        self.calls.append((method, name, namespace))
        if method in self.errors:
            raise self.errors[method]
        if method in self.conflicts:
            raise FakeApiException(409, "AlreadyExists")

    def create_namespace(self, *, body):
        self._call("create_namespace", body.metadata.name, "")

    def create_namespaced_secret(self, *, namespace, body):
        self._call("create_namespaced_secret", body.metadata.name, namespace)

    def replace_namespaced_secret(self, *, name, namespace, body):
        self._call("replace_namespaced_secret", name, namespace)

    def create_namespaced_pod(self, *, namespace, body):
        self._call("create_namespaced_pod", body.metadata.name, namespace)

    def create_namespaced_service(self, *, namespace, body):
        self._call("create_namespaced_service", body.metadata.name, namespace)

    def replace_namespaced_service(self, *, name, namespace, body):
        self._call("replace_namespaced_service", name, namespace)

    def read_namespaced_pod(self, *, name, namespace):
        self._call("read_namespaced_pod", name, namespace)
        return self.pods.popleft()


class FakeClientSet:
    def __init__(self, core_v1) -> None:
        self.core_v1 = core_v1
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
    def __init__(self, *, core_v1, api_exception_class) -> None:
        self.core_v1 = core_v1
        self.api_exception_class = api_exception_class
        self.reconciled_manifest = None
        self.ready_endpoint_url = ""

    def reconcile(self, manifest):
        self.reconciled_manifest = manifest
        return KubernetesReconcileResult(endpoint_url="http://runtime.test:8000")

    def wait_until_ready(self, manifest, *, endpoint_url):
        self.ready_endpoint_url = endpoint_url
        return KubernetesReconcileResult(
            endpoint_url=endpoint_url,
            pod=FakeKubernetesModel(),
            adapter_status={"ready": True},
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
        runtime_session_id=runtime_session_id,
        server_name=f"io.github.example/weather/{secret}",
        server_version="1.0.0+prod",
    )

    assert labels[KUBERNETES_LABEL_APP_NAME] == "wardn-mcp-runtime"
    assert labels[WARDN_LABEL_WORKSPACE_ID] == str(workspace_id)
    assert labels[WARDN_LABEL_INSTALLATION_ID] == str(installation_id)
    assert labels[WARDN_LABEL_RUNTIME_SESSION_ID] == str(runtime_session_id)
    assert secret not in labels[WARDN_LABEL_SERVER_NAME]
    assert secret not in repr(labels)


def test_kubernetes_provider_runtime_spec_uses_adapter_transport(tmp_path, monkeypatch) -> None:
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
        secret_config={
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


def test_kubernetes_runtime_manifest_uses_secret_refs_for_adapter_env(
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
        secret_config={"environment": {"WEATHER_TOKEN": "secret"}},
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
    expected_env_names = {
        WARDN_RUNTIME_COMMAND_ENV,
        WARDN_RUNTIME_ARGS_JSON_ENV,
        WARDN_RUNTIME_CWD_ENV,
        WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV,
        WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV,
        "WEATHER_TOKEN",
    }

    assert set(env_by_name) == expected_env_names
    assert manifest.secret.string_data[WARDN_RUNTIME_COMMAND_ENV] == "node"
    assert manifest.secret.string_data[WARDN_RUNTIME_ARGS_JSON_ENV] == '["weather-mcp"]'
    assert manifest.secret.string_data[WARDN_RUNTIME_CWD_ENV] == str(tmp_path)
    assert manifest.secret.string_data[WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV] == "7"
    assert manifest.secret.string_data[WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV] == "11"
    for env in env_by_name.values():
        assert getattr(env, "value", None) is None
        assert env.value_from.secret_key_ref.name == manifest.names.secret_name
        assert env.value_from.secret_key_ref.key == env.name


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
    assert not hasattr(manifest, "ingress")


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
        ".svc.cluster.local:8000"
    )
    assert core_v1.calls == [
        ("create_namespace", manifest.names.namespace, ""),
        ("create_namespaced_secret", manifest.names.secret_name, manifest.names.namespace),
        ("create_namespaced_pod", manifest.names.pod_name, manifest.names.namespace),
        ("create_namespaced_service", manifest.names.service_name, manifest.names.namespace),
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
        "create_namespaced_secret",
        "create_namespaced_service",
    }
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
    )

    reconciler.reconcile(manifest)

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
        "create_namespaced_pod",
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


def test_kubernetes_reconciler_waits_for_ready_pod() -> None:
    names = runtime_object_names(
        runtime_session_id=uuid.uuid4(),
        organization_id=None,
        workspace_id=uuid.uuid4(),
        prefix="wardn",
    )
    core_v1 = FakeCoreV1Api()
    core_v1.pods.extend(
        [
            fake_pod(phase="Pending", ready=False),
            fake_pod(phase="Running", ready=True),
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

    pod = reconciler.wait_for_pod_ready(names, timeout_seconds=5)

    assert pod_is_ready(pod) is True
    assert [call[0] for call in core_v1.calls] == [
        "read_namespaced_pod",
        "read_namespaced_pod",
    ]


def test_kubernetes_reconciler_rejects_terminal_pod_phase() -> None:
    names = runtime_object_names(
        runtime_session_id=uuid.uuid4(),
        organization_id=None,
        workspace_id=uuid.uuid4(),
        prefix="wardn",
    )
    core_v1 = FakeCoreV1Api()
    core_v1.pods.append(fake_pod(phase="Failed", message="image pull failed"))
    reconciler = KubernetesRuntimeReconciler(
        core_v1=core_v1,
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(KubernetesRuntimeNotReadyError, match="image pull failed"):
        reconciler.wait_for_pod_ready(names, timeout_seconds=5)


def test_kubernetes_reconciler_waits_for_adapter_ready(monkeypatch) -> None:
    seen = []
    statuses = iter(
        [
            {"ready": False},
            {"ready": True, "pid": 123},
        ]
    )

    def get_adapter_status(endpoint_url):
        seen.append(endpoint_url)
        return next(statuses)

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes.adapter_client.get_adapter_status",
        get_adapter_status,
    )
    ticks = iter([0, 1, 2])
    reconciler = KubernetesRuntimeReconciler(
        core_v1=FakeCoreV1Api(),
        api_exception_class=FakeApiException,
        settings=FakeSettings(),
        sleep=lambda seconds: None,
        monotonic=lambda: next(ticks),
    )

    status = reconciler.wait_for_adapter_ready("http://runtime.test:8000", timeout_seconds=5)

    assert status == {"ready": True, "pid": 123}
    assert seen == ["http://runtime.test:8000", "http://runtime.test:8000"]


def test_kubernetes_provider_reconciles_runtime_session_before_invocation_boundary(
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

    with pytest.raises(NotImplementedError, match="adapter HTTP invocation is not wired"):
        provider.call_tool(
            installation,
            tool_name="echo",
            arguments={},
            runtime_session=runtime_session,
        )

    assert fake_reconciler.reconciled_manifest is not None
    assert client_factory.load_count == 1
    assert fake_reconciler.ready_endpoint_url == "http://runtime.test:8000"
    assert runtime_session.namespace == fake_reconciler.reconciled_manifest.names.namespace
    assert runtime_session.pod_name == fake_reconciler.reconciled_manifest.names.pod_name
    assert runtime_session.endpoint_url == "http://runtime.test:8000"


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


def test_kubernetes_provider_health_reports_not_ready_for_active_session() -> None:
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider=RUNTIME_PROVIDER_KUBERNETES,
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )

    health = KubernetesRuntimeProvider().health(runtime_session)

    assert health.status == "not_ready"
    assert health.healthy is False
    assert health.ready is False
    assert (
        health.message
        == "Kubernetes runtime health polling is not wired into this endpoint yet."
    )
