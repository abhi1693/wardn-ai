import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.scheduled_tasks import worker
from app.modules.scheduled_tasks.models import WorkspaceScheduledTaskRun


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


def make_run() -> WorkspaceScheduledTaskRun:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    return WorkspaceScheduledTaskRun(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        task_id=uuid4(),
        agent_id=uuid4(),
        trigger_source="scheduled",
        status="running",
        scheduled_for=now,
        available_at=now,
        attempt_count=1,
        max_attempts=3,
        worker_id="worker-1",
        error="",
        delivery_summary={},
        created_at=now,
        updated_at=now,
    )


def test_retry_delay_uses_bounded_backoff() -> None:
    assert worker.retry_delay_seconds(1, base_seconds=30, max_seconds=300) == 30
    assert worker.retry_delay_seconds(4, base_seconds=30, max_seconds=300) == 240
    assert worker.retry_delay_seconds(8, base_seconds=30, max_seconds=300) == 300


@pytest.mark.asyncio
async def test_worker_once_claims_and_executes_scheduled_run(monkeypatch) -> None:
    run = make_run()
    seen = {}

    async def recover(session, *, now):
        seen["recover"] = session
        return 0

    async def enqueue(session, *, now):
        seen["enqueue"] = session
        return 1

    async def claim(session, **kwargs):
        seen["claim"] = (session, kwargs)
        return run

    async def execute(claimed_run, **kwargs):
        seen["execute"] = (claimed_run, kwargs)

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(worker.repository, "recover_expired_leases", recover)
    monkeypatch.setattr(worker.service, "enqueue_due_task_runs", enqueue)
    monkeypatch.setattr(worker.repository, "claim_next_run", claim)
    monkeypatch.setattr(worker, "execute_task_run", execute)

    worked = await worker.run_scheduled_task_worker_once(
        worker_id="worker-1",
        session_factory=session_factory,
        lease_seconds=300,
        heartbeat_seconds=30,
        retry_base_seconds=30,
        retry_max_seconds=300,
    )

    assert worked is True
    assert seen["recover"] is session_factory.sessions[0]
    assert seen["enqueue"] is session_factory.sessions[0]
    assert seen["claim"][0] is session_factory.sessions[0]
    assert seen["execute"][0] is run
    assert session_factory.sessions[0].committed is True


@pytest.mark.asyncio
async def test_worker_loop_sleeps_after_iteration_failure(monkeypatch) -> None:
    seen = {}

    async def fail_once(**kwargs):
        seen["worker"] = kwargs
        raise RuntimeError("database unavailable")

    async def stop_sleep(seconds):
        seen["sleep"] = seconds
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "run_scheduled_task_worker_once", fail_once)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_scheduled_task_worker_loop(
            worker_id="worker-1",
            poll_interval_seconds=10,
            session_factory=FakeSessionFactory(),
            lease_seconds=300,
            heartbeat_seconds=30,
            retry_base_seconds=30,
            retry_max_seconds=300,
            sleep=stop_sleep,
        )

    assert seen["sleep"] == 10
