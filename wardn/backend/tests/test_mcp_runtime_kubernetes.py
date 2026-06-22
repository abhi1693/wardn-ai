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
    KubernetesClientFactory,
    KubernetesConfigError,
    KubernetesImagePullSecretError,
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
    runtime_object_base_name,
    runtime_object_identity,
    runtime_object_names,
    runtime_object_names_for_session,
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
    mcp_runtime_kubernetes_service_port = 8000
    mcp_runtime_kubernetes_image_pull_secret_name = ""
    mcp_runtime_kubernetes_namespace_labels_json = "{}"
    mcp_runtime_kubernetes_namespace_annotations_json = "{}"
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


class FakeKubernetesModel:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeKubernetesClient:
    V1Container = FakeKubernetesModel
    V1ContainerPort = FakeKubernetesModel
    V1Deployment = FakeKubernetesModel
    V1DeploymentSpec = FakeKubernetesModel
    V1EnvVar = FakeKubernetesModel
    V1EnvVarSource = FakeKubernetesModel
    V1LabelSelector = FakeKubernetesModel
    V1LocalObjectReference = FakeKubernetesModel
    V1Namespace = FakeKubernetesModel
    V1ObjectMeta = FakeKubernetesModel
    V1Pod = FakeKubernetesModel
    V1PodSpec = FakeKubernetesModel
    V1PodTemplateSpec = FakeKubernetesModel
    V1Secret = FakeKubernetesModel
    V1SecretKeySelector = FakeKubernetesModel
    V1Service = FakeKubernetesModel
    V1ServicePort = FakeKubernetesModel
    V1ServiceSpec = FakeKubernetesModel
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


class FakeClientSet:
    def __init__(self, core_v1) -> None:
        self.core_v1 = core_v1
        self.apps_v1 = core_v1
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
    def __init__(self, *, core_v1, api_exception_class, apps_v1=None) -> None:
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1
        self.api_exception_class = api_exception_class
        self.reconciled_manifest = None
        self.ready_endpoint_url = ""

    def reconcile(self, manifest):
        self.reconciled_manifest = manifest
        return KubernetesReconcileResult(endpoint_url="http://runtime.test:8000/mcp")

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


def test_kubernetes_provider_runtime_spec_uses_streamable_http_transport(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes.get_settings",
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

    assert set(env_by_name) == {"WEATHER_TOKEN"}
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
    for env in env_by_name.values():
        assert getattr(env, "value", None) is None
        assert env.value_from.secret_key_ref.name == manifest.names.secret_name
        assert env.value_from.secret_key_ref.key == env.name


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


def test_kubernetes_runtime_manifest_rewrites_npm_host_paths_to_npx(
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

    assert supergateway_stdio_arg(manifest) == "npx --yes weather-mcp@1.2.3 --stdio"


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
    assert not hasattr(manifest, "ingress")


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
    assert core_v1.calls == [
        ("create_namespace", manifest.names.namespace, ""),
        ("create_namespaced_secret", manifest.names.secret_name, manifest.names.namespace),
        ("create_namespaced_deployment", manifest.names.pod_name, manifest.names.namespace),
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
        "create_namespaced_deployment",
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
        "replace_namespaced_deployment",
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

    def get_gateway_health(endpoint_url):
        seen.append(endpoint_url)
        return next(statuses)

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes.get_gateway_health",
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
    assert seen == ["http://runtime.test:8000/mcp", "http://runtime.test:8000/mcp"]


def test_kubernetes_provider_reconciles_and_invokes_supergateway_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes.get_settings",
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

    def call_tool(endpoint_url, headers, *, tool_name, arguments):
        seen["endpoint_url"] = endpoint_url
        seen["headers"] = headers
        seen["tool_name"] = tool_name
        seen["arguments"] = arguments
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes.mcp_client.call_tool",
        call_tool,
    )

    result = provider.call_tool(
        installation,
        tool_name="echo",
        arguments={"value": "ok"},
        runtime_session=runtime_session,
    )

    assert result == {"content": [{"type": "text", "text": "ok"}], "isError": False}
    assert seen == {
        "endpoint_url": "http://runtime.test:8000/mcp",
        "headers": {},
        "tool_name": "echo",
        "arguments": {"value": "ok"},
    }
    assert fake_reconciler.reconciled_manifest is not None
    assert client_factory.load_count == 1
    assert fake_reconciler.ready_endpoint_url == "http://runtime.test:8000/mcp"
    assert runtime_session.namespace == fake_reconciler.reconciled_manifest.names.namespace
    assert runtime_session.pod_name == fake_reconciler.reconciled_manifest.names.pod_name
    assert runtime_session.endpoint_url == "http://runtime.test:8000/mcp"

    second_result = provider.call_tool(
        installation,
        tool_name="echo",
        arguments={"value": "again"},
        runtime_session=runtime_session,
    )

    assert second_result["content"][0]["text"] == "ok"
    assert seen["arguments"] == {"value": "again"}


def test_kubernetes_provider_bubbles_supergateway_call_errors(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.kubernetes.get_settings",
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
        "app.modules.mcp_runtime.providers.kubernetes.mcp_client.call_tool",
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
        "app.modules.mcp_runtime.providers.kubernetes.get_settings",
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
        "app.modules.mcp_runtime.providers.kubernetes.get_settings",
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

    assert core_v1.calls == [
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
