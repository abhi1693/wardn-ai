import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.mcp_registry import catalog_jobs
from app.modules.mcp_registry.job_worker import MCPJobExecutionError
from app.modules.mcp_registry.models import MCPCatalogSource, MCPOperationJob
from app.modules.users.models import User

ORGANIZATION_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()


def catalog_source() -> MCPCatalogSource:
    timestamp = datetime.now(UTC)
    return MCPCatalogSource(
        id=SOURCE_ID,
        organization_id=ORGANIZATION_ID,
        name="Wardn Hub",
        provider="wardn_hub",
        base_url="https://hub.wardn.ai",
        tenant_id="",
        sync_mode="latest_only",
        is_enabled=True,
        last_error="",
        created_at=timestamp,
        updated_at=timestamp,
    )


def operation_job(source: MCPCatalogSource) -> MCPOperationJob:
    timestamp = datetime.now(UTC)
    return MCPOperationJob(
        id=uuid.uuid4(),
        organization_id=ORGANIZATION_ID,
        workspace_id=None,
        operation=catalog_jobs.SYNC_CATALOG_SOURCE_OPERATION,
        resource_key=catalog_jobs.catalog_source_resource_key(ORGANIZATION_ID, source.id),
        deduplication_key=uuid.uuid4().hex,
        status="running",
        request_payload={
            "sourceId": str(source.id),
            "sourceRevision": catalog_jobs.catalog_source_revision(source),
        },
        result={},
        progress_current=0,
        progress_total=3,
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
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeSessionFactory:
    def __init__(self) -> None:
        self.session = FakeSession()

    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext(self.session)


class FakeReporter:
    def __init__(self) -> None:
        self.progress: list[tuple[int, int, str]] = []

    async def update(self, current, total, message, *, details=None) -> None:
        self.progress.append((current, total, message))


@pytest.mark.asyncio
async def test_enqueue_catalog_sync_records_source_revision(monkeypatch) -> None:
    source = catalog_source()
    user = User(id=uuid.uuid4(), email="admin@example.com")
    seen: dict[str, object] = {}

    async def get_source(*args, **kwargs):
        return source

    async def enqueue(*args, **kwargs):
        seen.update(kwargs)
        return "queued-job"

    monkeypatch.setattr(catalog_jobs.repository, "get_catalog_source", get_source)
    monkeypatch.setattr(catalog_jobs, "enqueue_operation_job", enqueue)

    result = await catalog_jobs.enqueue_catalog_source_sync(
        object(),
        organization_id=ORGANIZATION_ID,
        source_id=source.id,
        user=user,
    )

    assert result == "queued-job"
    assert seen["operation"] == "sync_catalog_source"
    assert seen["workspace_id"] is None
    assert seen["request_payload"] == {
        "sourceId": str(source.id),
        "sourceRevision": catalog_jobs.catalog_source_revision(source),
    }


@pytest.mark.asyncio
async def test_catalog_worker_persists_success_and_progress(monkeypatch) -> None:
    source = catalog_source()
    job = operation_job(source)
    reporter = FakeReporter()
    session_factory = FakeSessionFactory()

    async def get_source(*args, **kwargs):
        return source

    async def sync(*args, **kwargs):
        return SimpleNamespace(
            synced_count=7,
            model_dump=lambda **options: {"source": {"id": str(source.id)}, "syncedCount": 7},
        )

    monkeypatch.setattr(catalog_jobs, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(catalog_jobs.repository, "get_catalog_source", get_source)
    monkeypatch.setattr(catalog_jobs.service, "sync_catalog_source", sync)

    result = await catalog_jobs.execute_catalog_source_sync(job, reporter)

    assert result["syncedCount"] == 7
    assert session_factory.session.commit_count == 1
    assert reporter.progress[-1] == (3, 3, "Synchronized 7 server definitions")


@pytest.mark.asyncio
async def test_catalog_worker_commits_source_error_before_retry(monkeypatch) -> None:
    source = catalog_source()
    job = operation_job(source)
    session_factory = FakeSessionFactory()

    async def get_source(*args, **kwargs):
        return source

    async def fail_sync(*args, **kwargs):
        raise ValueError("catalog sync failed: registry offline")

    monkeypatch.setattr(catalog_jobs, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(catalog_jobs.repository, "get_catalog_source", get_source)
    monkeypatch.setattr(catalog_jobs.service, "sync_catalog_source", fail_sync)

    with pytest.raises(MCPJobExecutionError) as error:
        await catalog_jobs.execute_catalog_source_sync(job, FakeReporter())

    assert error.value.code == "catalog_sync_failed"
    assert error.value.retryable is True
    assert session_factory.session.commit_count == 1


@pytest.mark.asyncio
async def test_catalog_worker_rejects_source_changed_after_enqueue(monkeypatch) -> None:
    source = catalog_source()
    job = operation_job(source)
    source.base_url = "https://changed.example.com"
    session_factory = FakeSessionFactory()

    async def get_source(*args, **kwargs):
        return source

    monkeypatch.setattr(catalog_jobs, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(catalog_jobs.repository, "get_catalog_source", get_source)

    with pytest.raises(MCPJobExecutionError) as error:
        await catalog_jobs.execute_catalog_source_sync(job, FakeReporter())

    assert error.value.code == "catalog_source_changed"
    assert error.value.retryable is False
