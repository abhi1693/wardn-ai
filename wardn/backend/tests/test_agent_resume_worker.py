from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.agents import resume_worker
from app.modules.agents.models import AgentRunResumeJob
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rolled_back = False

    async def commit(self) -> None:
        self.commits += 1

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


def make_resume_job() -> AgentRunResumeJob:
    now = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
    return AgentRunResumeJob(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        agent_run_id=uuid4(),
        approval_id=uuid4(),
        user_id=uuid4(),
        status="running",
        available_at=now,
        started_at=now,
        finished_at=None,
        attempt_count=1,
        max_attempts=3,
        worker_id="worker-1",
        lease_expires_at=now + timedelta(seconds=60),
        error="",
        payload={"toolName": "scale_deployment"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_worker_once_recovers_stale_approvals_before_claiming(monkeypatch) -> None:
    job = make_resume_job()
    seen: dict[str, object] = {}

    async def recover(session, *, now):
        seen["recover"] = (session, now)
        return 1

    async def enqueue_stale(session, *, now, stale_before):
        seen["enqueue_stale"] = (session, now, stale_before)
        return 2

    async def claim(session, **kwargs):
        seen["claim"] = (session, kwargs)
        return job

    async def execute(claimed_job, **kwargs):
        seen["execute"] = (claimed_job, kwargs)

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(
        resume_worker.repository,
        "recover_expired_agent_run_resume_jobs",
        recover,
    )
    monkeypatch.setattr(
        resume_worker.repository,
        "enqueue_stale_agent_run_resume_jobs",
        enqueue_stale,
    )
    monkeypatch.setattr(
        resume_worker.repository,
        "claim_next_agent_run_resume_job",
        claim,
    )
    monkeypatch.setattr(resume_worker, "execute_agent_run_resume_job", execute)

    worked = await resume_worker.run_agent_run_resume_worker_once(
        worker_id="worker-1",
        session_factory=session_factory,
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    session = session_factory.sessions[0]
    stale_now = seen["enqueue_stale"][1]
    stale_before = seen["enqueue_stale"][2]
    assert worked is True
    assert seen["recover"][0] is session
    assert seen["enqueue_stale"][0] is session
    assert stale_now - stale_before == timedelta(seconds=60)
    assert seen["claim"][0] is session
    assert seen["execute"][0] is job
    assert session.commits == 1


@pytest.mark.asyncio
async def test_worker_once_counts_stale_requeue_as_work_without_claim(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def recover(session, *, now):
        return 0

    async def enqueue_stale(session, *, now, stale_before):
        seen["enqueue_stale"] = session
        return 1

    async def claim(session, **kwargs):
        seen["claim"] = session
        return None

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(
        resume_worker.repository,
        "recover_expired_agent_run_resume_jobs",
        recover,
    )
    monkeypatch.setattr(
        resume_worker.repository,
        "enqueue_stale_agent_run_resume_jobs",
        enqueue_stale,
    )
    monkeypatch.setattr(
        resume_worker.repository,
        "claim_next_agent_run_resume_job",
        claim,
    )

    worked = await resume_worker.run_agent_run_resume_worker_once(
        worker_id="worker-1",
        session_factory=session_factory,
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    assert worked is True
    assert seen["enqueue_stale"] is session_factory.sessions[0]
    assert seen["claim"] is session_factory.sessions[0]
    assert session_factory.sessions[0].commits == 1


@pytest.mark.asyncio
async def test_execute_resume_job_continues_approved_run_and_marks_job_complete(
    monkeypatch,
) -> None:
    job = make_resume_job()
    user = User(id=job.user_id, email="owner@example.com", is_active=True)
    seen: dict[str, object] = {}

    async def get_owned(session, job_id, *, worker_id):
        seen["get_owned"] = (session, job_id, worker_id)
        return job

    async def get_user(session, user_id):
        seen["get_user"] = (session, user_id)
        return user

    async def append_step(session, *, agent_run_id, step_type, status, title, payload):
        seen["append_step"] = (session, agent_run_id, step_type, status, title, payload)

    async def complete_approval(
        session,
        user_arg,
        organization_id,
        workspace_id,
        agent_id,
        approval_id,
        *,
        checkpoint_after_execution,
    ):
        seen["complete_approval"] = (
            session,
            user_arg,
            organization_id,
            workspace_id,
            agent_id,
            approval_id,
        )
        await checkpoint_after_execution()

    async def complete_job(session, job_id, *, worker_id, now):
        seen["complete_job"] = (session, job_id, worker_id, now)
        return True

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(
        resume_worker.repository,
        "get_owned_agent_run_resume_job",
        get_owned,
    )
    monkeypatch.setattr(resume_worker.users_repository, "get_user_by_id", get_user)
    monkeypatch.setattr(resume_worker.repository, "append_agent_run_step", append_step)
    monkeypatch.setattr(
        resume_worker.approvals,
        "complete_agent_tool_approval",
        complete_approval,
    )
    monkeypatch.setattr(
        resume_worker.repository,
        "complete_agent_run_resume_job",
        complete_job,
    )

    await resume_worker.execute_agent_run_resume_job(
        job,
        worker_id="worker-1",
        session_factory=session_factory,
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    session = session_factory.sessions[0]
    assert seen["get_owned"] == (session, job.id, "worker-1")
    assert seen["get_user"] == (session, user.id)
    assert seen["append_step"][2:5] == (
        "approval_resume_running",
        "running",
        "Approval resume",
    )
    assert seen["complete_approval"][:2] == (session, user)
    assert seen["complete_approval"][2:] == (
        job.organization_id,
        job.workspace_id,
        job.agent_id,
        job.approval_id,
    )
    assert seen["complete_job"][0:3] == (session, job.id, "worker-1")
    assert session.commits == 2


@pytest.mark.asyncio
async def test_execute_resume_job_retries_when_continuation_fails(monkeypatch) -> None:
    job = make_resume_job()
    user = User(id=job.user_id, email="owner@example.com", is_active=True)
    seen: dict[str, object] = {}

    async def get_owned(*args, **kwargs):
        return job

    async def get_user(*args, **kwargs):
        return user

    async def append_step(*args, **kwargs):
        return None

    async def complete_approval(*args, **kwargs):
        raise RuntimeError("model unavailable")

    async def retry_or_fail(**kwargs):
        seen["retry"] = kwargs

    monkeypatch.setattr(
        resume_worker.repository,
        "get_owned_agent_run_resume_job",
        get_owned,
    )
    monkeypatch.setattr(resume_worker.users_repository, "get_user_by_id", get_user)
    monkeypatch.setattr(resume_worker.repository, "append_agent_run_step", append_step)
    monkeypatch.setattr(
        resume_worker.approvals,
        "complete_agent_tool_approval",
        complete_approval,
    )
    monkeypatch.setattr(
        resume_worker,
        "retry_or_fail_claimed_resume_job",
        retry_or_fail,
    )

    await resume_worker.execute_agent_run_resume_job(
        job,
        worker_id="worker-1",
        session_factory=FakeSessionFactory(),
        lease_seconds=60,
        heartbeat_seconds=10,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    assert seen["retry"]["job"] is job
    assert seen["retry"]["worker_id"] == "worker-1"
    assert str(seen["retry"]["exc"]) == "model unavailable"
