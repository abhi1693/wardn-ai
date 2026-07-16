import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.mcp_registry import installation_jobs
from app.modules.mcp_registry.job_worker import MCPJobCleanupError, MCPJobExecutionError
from app.modules.mcp_registry.models import (
    MCPOperationJob,
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.mcp_registry.schemas import MCPServerBulkUpdateRequest, MCPServerInstallRequest
from app.modules.users.models import User

ORGANIZATION_ID = uuid.uuid4()
WORKSPACE_ID = uuid.uuid4()


def server_version() -> MCPServerVersion:
    return MCPServerVersion(
        organization_id=ORGANIZATION_ID,
        name="io.github.example/weather",
        title="Weather",
        description="Weather server",
        version="1.0.0",
        server_json={
            "$schema": "https://example.com/server.schema.json",
            "name": "io.github.example/weather",
            "description": "Weather server",
            "version": "1.0.0",
        },
        status="active",
        status_message="",
        is_latest=True,
        packages=[],
        remotes=[],
    )


def operation_job(payload: dict) -> MCPOperationJob:
    timestamp = datetime.now(UTC)
    return MCPOperationJob(
        id=uuid.uuid4(),
        organization_id=ORGANIZATION_ID,
        workspace_id=WORKSPACE_ID,
        operation=installation_jobs.INSTALL_SERVER_OPERATION,
        resource_key=installation_jobs.workspace_installations_resource_key(WORKSPACE_ID),
        deduplication_key=uuid.uuid4().hex,
        status="running",
        request_payload=payload,
        result={},
        progress_current=0,
        progress_total=4,
        progress_message="Starting",
        attempt_count=1,
        max_attempts=3,
        available_at=timestamp,
        worker_id="worker-1",
        error_code="",
        error_message="",
        cleanup_status="not_required",
        cleanup_payload={},
        cleanup_attempt_count=0,
        cleanup_max_attempts=5,
        cleanup_worker_id="",
        cleanup_error="",
        created_at=timestamp,
        updated_at=timestamp,
    )


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSessionContext:
        session = FakeSession()
        self.sessions.append(session)
        return FakeSessionContext(session)


class FakeReporter:
    def __init__(self) -> None:
        self.progress: list[tuple[int, int, str]] = []
        self.cleanup: list[dict] = []

    async def update(self, current, total, message, *, details=None) -> None:
        self.progress.append((current, total, message))

    async def register_cleanup(self, payload) -> None:
        self.cleanup.append(payload)


@pytest.mark.asyncio
async def test_enqueue_installation_externalizes_secrets_before_persisting_job(monkeypatch) -> None:
    server = server_version()
    user = User(id=uuid.uuid4(), email="admin@example.com")
    seen: dict[str, object] = {}

    async def get_server(*args, **kwargs):
        return server

    async def no_existing_job(*args, **kwargs):
        return None

    async def get_installation(*args, **kwargs):
        return None

    async def require_capacity(*args, **kwargs):
        seen["capacity"] = kwargs

    async def externalize(*args, **kwargs):
        return {
            "WEATHER_TOKEN": {
                "type": "secret_handle",
                "secretHandleId": str(uuid.uuid4()),
            }
        }

    async def enqueue(*args, **kwargs):
        seen["job"] = kwargs
        return "queued-job"

    monkeypatch.setattr(installation_jobs.repository, "get_server_version", get_server)
    monkeypatch.setattr(
        installation_jobs.job_repository,
        "get_active_job_by_deduplication_key",
        no_existing_job,
    )
    monkeypatch.setattr(installation_jobs.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_jobs, "require_new_installation_capacity", require_capacity)
    monkeypatch.setattr(
        installation_jobs.service,
        "externalize_install_config_secrets",
        externalize,
    )
    monkeypatch.setattr(installation_jobs, "enqueue_operation_job", enqueue)

    result = await installation_jobs.enqueue_server_installation(
        object(),
        organization_id=ORGANIZATION_ID,
        workspace_id=WORKSPACE_ID,
        user=user,
        server_name=server.name,
        payload=MCPServerInstallRequest(
            version="latest",
            configValues={"WEATHER_TOKEN": "raw-secret"},
            configSecretStoreId=uuid.uuid4(),
        ),
    )

    assert result == "queued-job"
    request_payload = seen["job"]["request_payload"]
    assert request_payload["desiredState"]["version"] == "1.0.0"
    assert "raw-secret" not in str(request_payload)
    assert request_payload["desiredState"]["configSecretStoreId"] is None
    assert seen["job"]["resource_key"] == (
        f"workspace:{WORKSPACE_ID}:mcp-installations"
    )


@pytest.mark.asyncio
async def test_enqueue_installation_reuses_retry_before_writing_secret_again(monkeypatch) -> None:
    server = server_version()
    user = User(id=uuid.uuid4(), email="admin@example.com")
    payload = MCPServerInstallRequest(
        configValues={"WEATHER_TOKEN": "raw-secret"},
        configSecretStoreId=uuid.uuid4(),
    )
    existing = operation_job({"serverName": server.name, "desiredState": {}})
    existing.status = "queued"
    existing.cleanup_available_at = None

    async def existing_job(*args, **kwargs):
        return existing

    async def list_events(*args, **kwargs):
        return []

    async def must_not_externalize(*args, **kwargs):
        raise AssertionError("an idempotent retry must not write the raw secret again")

    monkeypatch.setattr(
        installation_jobs.job_repository,
        "get_active_job_by_deduplication_key",
        existing_job,
    )
    monkeypatch.setattr(installation_jobs.job_repository, "list_job_events", list_events)
    monkeypatch.setattr(
        installation_jobs.service,
        "externalize_install_config_secrets",
        must_not_externalize,
    )

    response = await installation_jobs.enqueue_server_installation(
        object(),
        organization_id=ORGANIZATION_ID,
        workspace_id=WORKSPACE_ID,
        user=user,
        server_name=server.name,
        payload=payload,
    )

    assert response.job_id == existing.id


@pytest.mark.asyncio
async def test_worker_executes_install_and_clears_retryable_cleanup(monkeypatch) -> None:
    server = server_version()
    desired_state = MCPServerInstallRequest(version="1.0.0").model_dump(
        mode="json",
        by_alias=True,
    )
    job = operation_job({"serverName": server.name, "desiredState": desired_state})
    reporter = FakeReporter()
    session_factory = FakeSessionFactory()

    async def get_server(*args, **kwargs):
        return server

    async def install(*args, **kwargs):
        return SimpleNamespace(
            model_dump=lambda **options: {
                "id": str(uuid.uuid4()),
                "serverName": server.name,
            }
        )

    monkeypatch.setattr(installation_jobs, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(installation_jobs.repository, "get_server_version", get_server)
    monkeypatch.setattr(installation_jobs.service, "install_server_version", install)

    result = await installation_jobs.execute_server_installation(job, reporter)

    assert result["installation"]["serverName"] == server.name
    assert session_factory.sessions[0].committed is True
    assert reporter.cleanup[0]["paths"][0].endswith(".tmp")
    assert reporter.cleanup[0]["paths"][1].endswith(".backup")
    assert reporter.cleanup[-1] == {}
    assert reporter.progress[-1] == (3, 4, f"Installed {server.name}")


@pytest.mark.asyncio
async def test_bulk_update_records_exact_versions_and_secret_handles(monkeypatch) -> None:
    server = server_version()
    handle_id = uuid.uuid4()
    installation = MCPServerInstallation(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        server_name=server.name,
        config_name="production",
        installed_version="0.9.0",
        install_type="package",
        status="enabled",
        secret_references={
            "environment": {
                "WEATHER_TOKEN": {
                    "type": "secret_handle",
                    "secretHandleId": str(handle_id),
                }
            }
        },
    )
    user = User(id=uuid.uuid4(), email="admin@example.com")
    seen: dict[str, object] = {}

    async def list_installations(*args, **kwargs):
        return [installation]

    async def get_server(*args, **kwargs):
        return server

    async def enqueue(*args, **kwargs):
        seen.update(kwargs)
        return "queued-job"

    monkeypatch.setattr(
        installation_jobs.repository,
        "list_installations_for_server",
        list_installations,
    )
    monkeypatch.setattr(installation_jobs.repository, "get_server_version", get_server)
    monkeypatch.setattr(installation_jobs, "enqueue_operation_job", enqueue)

    result = await installation_jobs.enqueue_installed_server_updates(
        object(),
        organization_id=ORGANIZATION_ID,
        workspace_id=WORKSPACE_ID,
        user=user,
        payload=MCPServerBulkUpdateRequest(serverNames=[server.name]),
    )

    assert result == "queued-job"
    target = seen["request_payload"]["targets"][0]
    assert target["desiredState"]["version"] == "1.0.0"
    assert target["desiredState"]["configName"] == "production"
    assert target["desiredState"]["configValues"]["WEATHER_TOKEN"] == {
        "type": "secret_handle",
        "secretHandleId": str(handle_id),
    }


@pytest.mark.asyncio
async def test_bulk_worker_executes_each_persisted_target(monkeypatch) -> None:
    server = server_version()
    desired_state = MCPServerInstallRequest(version="1.0.0").model_dump(
        mode="json",
        by_alias=True,
    )
    targets = [
        {"serverName": server.name, "desiredState": desired_state},
        {"serverName": "io.github.example/alerts", "desiredState": desired_state},
    ]
    job = operation_job({"targets": targets})
    job.operation = installation_jobs.BULK_UPDATE_SERVERS_OPERATION
    seen: list[dict] = []

    async def execute_target(*args, **kwargs):
        seen.append(kwargs)
        return {"serverName": kwargs["server_name"]}

    monkeypatch.setattr(installation_jobs, "execute_installation_target", execute_target)

    result = await installation_jobs.execute_installed_server_updates(job, FakeReporter())

    assert [item["serverName"] for item in result["installations"]] == [
        server.name,
        "io.github.example/alerts",
    ]
    assert [item["progress_start"] for item in seen] == [1, 4]
    assert all(item["progress_total"] == 6 for item in seen)


def test_installation_error_classification_distinguishes_permanent_errors() -> None:
    permanent = installation_jobs.classify_installation_error(ValueError("invalid target"))
    transient = installation_jobs.classify_installation_error(RuntimeError("registry offline"))

    assert isinstance(permanent, MCPJobExecutionError)
    assert permanent.retryable is False
    assert transient.retryable is True


def test_cleanup_rejects_paths_outside_managed_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(installation_jobs, "default_install_root", lambda: tmp_path / "managed")

    with pytest.raises(MCPJobCleanupError, match="outside"):
        installation_jobs.remove_retryable_install_paths(
            {"paths": [str(tmp_path / "outside.tmp")]}
        )


def test_cleanup_removes_only_temporary_managed_paths(tmp_path, monkeypatch) -> None:
    root = tmp_path / "managed"
    temporary_path = root / "server" / "1.0.0.tmp"
    temporary_path.mkdir(parents=True)
    (temporary_path / "partial").write_text("data", encoding="utf-8")
    monkeypatch.setattr(installation_jobs, "default_install_root", lambda: root)

    installation_jobs.remove_retryable_install_paths({"paths": [str(temporary_path)]})

    assert not temporary_path.exists()
