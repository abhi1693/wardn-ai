import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.mcp_registry import job_repository
from app.modules.mcp_registry.models import MCPOperationJob, MCPOperationJobEvent


def make_job(
    *,
    status: str = "queued",
    attempt_count: int = 0,
    max_attempts: int = 3,
) -> MCPOperationJob:
    timestamp = datetime.now(UTC)
    return MCPOperationJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        operation="install_server",
        resource_key="workspace:test/server:example",
        deduplication_key=uuid.uuid4().hex,
        status=status,
        request_payload={},
        result={},
        progress_current=0,
        progress_total=4,
        progress_message="Queued",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        available_at=timestamp,
        worker_id="",
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


class FakeScalarResult:
    def __init__(self, values: list[MCPOperationJob]) -> None:
        self.values = values

    def all(self) -> list[MCPOperationJob]:
        return self.values


class FakeResult:
    def __init__(self, values: list[MCPOperationJob]) -> None:
        self.values = values

    def scalar_one_or_none(self) -> MCPOperationJob | None:
        return self.values[0] if self.values else None

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self.values)


class FakeSession:
    def __init__(self, *results: list[MCPOperationJob]) -> None:
        self.results = list(results)
        self.added: list[object] = []
        self.flushed = False

    async def execute(self, statement) -> FakeResult:
        return FakeResult(self.results.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_claim_next_job_persists_lease_attempt_and_event() -> None:
    job = make_job()
    session = FakeSession([job])
    now = datetime.now(UTC)

    claimed = await job_repository.claim_next_job(
        session,
        worker_id="worker-1",
        now=now,
        lease_seconds=90,
    )

    assert claimed is job
    assert job.status == "running"
    assert job.worker_id == "worker-1"
    assert job.attempt_count == 1
    assert job.started_at == now
    assert job.lease_expires_at == now + timedelta(seconds=90)
    assert session.flushed is True
    assert len(session.added) == 1
    event = session.added[0]
    assert isinstance(event, MCPOperationJobEvent)
    assert event.event_type == "started"


@pytest.mark.asyncio
async def test_failure_requeues_until_attempt_limit() -> None:
    job = make_job(status="running", attempt_count=1, max_attempts=3)
    job.worker_id = "worker-1"
    session = FakeSession([job])
    now = datetime.now(UTC)
    retry_at = now + timedelta(seconds=30)

    result = await job_repository.retry_or_fail_job(
        session,
        job.id,
        worker_id="worker-1",
        now=now,
        retry_at=retry_at,
        error_code="install_failed",
        error_message="package manager failed",
        retryable=True,
    )

    assert result == "queued"
    assert job.status == "queued"
    assert job.available_at == retry_at
    assert job.completed_at is None
    assert job.worker_id == ""
    assert job.error_code == "install_failed"


@pytest.mark.asyncio
async def test_terminal_failure_makes_registered_cleanup_claimable() -> None:
    job = make_job(status="running", attempt_count=3, max_attempts=3)
    job.worker_id = "worker-1"
    job.cleanup_payload = {"temporaryPath": "/install/.tmp/job-1"}
    job.cleanup_status = "pending"
    session = FakeSession([job])
    now = datetime.now(UTC)

    result = await job_repository.retry_or_fail_job(
        session,
        job.id,
        worker_id="worker-1",
        now=now,
        retry_at=now + timedelta(seconds=30),
        error_code="install_failed",
        error_message="package manager failed",
        retryable=True,
    )

    assert result == "failed"
    assert job.status == "failed"
    assert job.completed_at == now
    assert job.cleanup_status == "pending"
    assert job.cleanup_available_at == now


@pytest.mark.asyncio
async def test_cleanup_failure_has_independent_retry_budget() -> None:
    job = make_job(status="failed")
    job.cleanup_status = "running"
    job.cleanup_worker_id = "worker-1"
    job.cleanup_attempt_count = 2
    job.cleanup_max_attempts = 5
    session = FakeSession([job])
    retry_at = datetime.now(UTC) + timedelta(seconds=30)

    result = await job_repository.retry_or_fail_cleanup(
        session,
        job.id,
        worker_id="worker-1",
        retry_at=retry_at,
        error_message="filesystem busy",
        retryable=True,
    )

    assert result == "pending"
    assert job.cleanup_status == "pending"
    assert job.cleanup_available_at == retry_at
    assert job.cleanup_attempt_count == 2
    assert job.cleanup_error == "filesystem busy"


@pytest.mark.asyncio
async def test_expired_lease_is_requeued_and_audited() -> None:
    job = make_job(status="running", attempt_count=1, max_attempts=3)
    job.worker_id = "dead-worker"
    now = datetime.now(UTC)
    job.lease_expires_at = now - timedelta(seconds=1)
    session = FakeSession([job], [])

    recovered = await job_repository.recover_expired_leases(session, now=now)

    assert recovered == 1
    assert job.status == "queued"
    assert job.worker_id == ""
    assert job.error_code == "worker_lease_expired"
    assert isinstance(session.added[0], MCPOperationJobEvent)
    assert session.added[0].event_type == "lease_expired"
