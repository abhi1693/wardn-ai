import argparse
import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.commands.registry import CommandRegistry
from app.core.config import Settings
from app.modules.mcp_registry import job_commands, job_repository, job_worker
from app.modules.mcp_registry.models import MCPOperationJob


def make_job(*, operation: str = "install_server") -> MCPOperationJob:
    timestamp = datetime.now(UTC)
    return MCPOperationJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        operation=operation,
        resource_key="workspace:test/server:example",
        deduplication_key=uuid.uuid4().hex,
        status="running",
        request_payload={},
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
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


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


def test_claim_statement_serializes_jobs_for_the_same_resource() -> None:
    statement = job_repository.claimable_job_statement(datetime.now(UTC))

    sql = str(statement.compile(dialect=postgresql.dialect())).upper()

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "NOT (EXISTS" in sql
    assert "RESOURCE_KEY" in sql
    assert "STATUS IN" in sql


def test_retry_delay_uses_bounded_exponential_backoff() -> None:
    assert job_worker.retry_delay_seconds(1, base_seconds=10, max_seconds=60) == 10
    assert job_worker.retry_delay_seconds(3, base_seconds=10, max_seconds=60) == 40
    assert job_worker.retry_delay_seconds(10, base_seconds=10, max_seconds=60) == 60


@pytest.mark.asyncio
async def test_execute_job_persists_success(monkeypatch) -> None:
    job = make_job()
    seen: dict[str, object] = {}

    async def executor(claimed_job, reporter):
        seen["executor"] = (claimed_job, reporter.worker_id)
        return {"installationId": "installation-1"}

    async def persist_success(**kwargs):
        seen["success"] = kwargs

    monkeypatch.setattr(job_worker, "persist_job_success", persist_success)

    await job_worker.execute_job(
        job,
        worker_id="worker-1",
        handlers=job_worker.MCPJobHandlers(
            executors={"install_server": executor},
            cleanup_executors={},
        ),
        session_factory=FakeSessionFactory(),
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    assert seen["executor"] == (job, "worker-1")
    assert seen["success"]["result"] == {"installationId": "installation-1"}


@pytest.mark.asyncio
async def test_execute_job_persists_non_retryable_unknown_operation(monkeypatch) -> None:
    job = make_job(operation="unknown")
    seen: dict[str, object] = {}

    async def persist_failure(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(job_worker, "persist_job_failure", persist_failure)

    await job_worker.execute_job(
        job,
        worker_id="worker-1",
        handlers=job_worker.MCPJobHandlers(executors={}, cleanup_executors={}),
        session_factory=FakeSessionFactory(),
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    error = seen["exc"]
    assert isinstance(error, job_worker.MCPJobExecutionError)
    assert error.code == "unsupported_operation"
    assert error.retryable is False


@pytest.mark.asyncio
async def test_run_worker_once_recovers_and_claims_job(monkeypatch) -> None:
    job = make_job()
    seen: dict[str, object] = {}

    async def recover(session, *, now):
        seen["recovered"] = session
        return 1

    async def claim_cleanup(*args, **kwargs):
        return None

    async def claim_job(session, **kwargs):
        seen["claim"] = (session, kwargs)
        return job

    async def execute(claimed_job, **kwargs):
        seen["execute"] = (claimed_job, kwargs)

    monkeypatch.setattr(job_worker.job_repository, "recover_expired_leases", recover)
    monkeypatch.setattr(job_worker.job_repository, "claim_next_cleanup", claim_cleanup)
    monkeypatch.setattr(job_worker.job_repository, "claim_next_job", claim_job)
    monkeypatch.setattr(job_worker, "execute_job", execute)
    session_factory = FakeSessionFactory()

    worked = await job_worker.run_job_worker_once(
        worker_id="worker-1",
        handlers=job_worker.MCPJobHandlers(executors={}, cleanup_executors={}),
        session_factory=session_factory,
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    assert worked is True
    assert seen["recovered"] is session_factory.sessions[0]
    assert seen["claim"][0] is session_factory.sessions[0]
    assert seen["execute"][0] is job
    assert session_factory.sessions[0].committed is True


@pytest.mark.asyncio
async def test_worker_loop_sleeps_after_database_failure(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fail_once(**kwargs):
        seen["worker"] = kwargs
        raise RuntimeError("database unavailable")

    async def stop_sleep(seconds):
        seen["sleep"] = seconds
        raise asyncio.CancelledError

    monkeypatch.setattr(job_worker, "run_job_worker_once", fail_once)

    with pytest.raises(asyncio.CancelledError):
        await job_worker.run_job_worker_loop(
            worker_id="worker-1",
            handlers=job_worker.MCPJobHandlers(executors={}, cleanup_executors={}),
            poll_interval_seconds=2.5,
            session_factory=FakeSessionFactory(),
            lease_seconds=60,
            heartbeat_seconds=10,
            retry_base_seconds=5,
            retry_max_seconds=30,
            sleep=stop_sleep,
        )

    assert seen["sleep"] == 2.5


def test_worker_settings_require_container_isolation_outside_local() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        mcp_runtime_provider="kubernetes",
        mcp_job_worker_isolation="process",
        api_token_secret="production-api-token-secret-that-is-unique",
        session_secret="production-session-secret-that-is-unique",
    )

    with pytest.raises(ValueError, match="isolated container or pod"):
        job_commands.validate_worker_settings(settings, poll_interval_seconds=2)

    settings.mcp_job_worker_isolation = "container"
    job_commands.validate_worker_settings(settings, poll_interval_seconds=2)


def test_register_mcp_job_command() -> None:
    registry = CommandRegistry()
    job_commands.register_mcp_job_commands(registry)

    args = registry.build_parser().parse_args(
        ["runmcpjobs", "--once", "--worker-id", "worker-1", "--poll-interval", "3"]
    )

    assert args == argparse.Namespace(
        command="runmcpjobs",
        once=True,
        worker_id="worker-1",
        poll_interval=3.0,
        verbose=False,
        handler=job_commands.handle_runmcpjobs,
    )


@pytest.mark.asyncio
async def test_continuous_worker_owns_runtime_maintenance(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    warmup_task = object()
    reaper_task = object()
    seen = {}

    monkeypatch.setattr(job_commands, "get_settings", lambda: settings)
    monkeypatch.setattr(
        job_commands,
        "build_job_handlers",
        lambda: job_worker.MCPJobHandlers(executors={}, cleanup_executors={}),
    )
    monkeypatch.setattr(
        job_commands,
        "start_runtime_warmup",
        lambda **kwargs: seen.setdefault("warmup_start", (kwargs, warmup_task))[1],
    )
    monkeypatch.setattr(
        job_commands,
        "start_runtime_reaper",
        lambda **kwargs: seen.setdefault("reaper_start", (kwargs, reaper_task))[1],
    )

    async def stop_runtime_warmup(task):
        seen["warmup_stop"] = task

    async def stop_runtime_reaper(task):
        seen["reaper_stop"] = task

    async def cancel_worker_loop(**kwargs):
        seen["worker"] = kwargs
        raise asyncio.CancelledError

    monkeypatch.setattr(job_commands, "stop_runtime_warmup", stop_runtime_warmup)
    monkeypatch.setattr(job_commands, "stop_runtime_reaper", stop_runtime_reaper)
    monkeypatch.setattr(job_commands, "run_job_worker_loop", cancel_worker_loop)

    args = argparse.Namespace(
        once=False,
        worker_id="worker-1",
        poll_interval=3.0,
        verbose=False,
    )
    with pytest.raises(asyncio.CancelledError):
        await job_commands.run_mcp_jobs_from_args(args)

    assert seen["warmup_start"][0] == {
        "concurrency": settings.mcp_runtime_warm_startup_concurrency
    }
    assert seen["reaper_start"][0] == {
        "interval_seconds": settings.mcp_runtime_reaper_interval_seconds,
        "limit": settings.mcp_runtime_reaper_batch_size,
        "event_retention_days": settings.mcp_runtime_event_retention_days,
        "invocation_retention_days": settings.mcp_runtime_invocation_retention_days,
    }
    assert seen["warmup_stop"] is warmup_task
    assert seen["reaper_stop"] is reaper_task
