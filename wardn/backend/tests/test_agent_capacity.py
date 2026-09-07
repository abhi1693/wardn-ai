from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.agents import capacity
from app.modules.agents.exceptions import AgentCapacityUnavailableError
from app.modules.limits import service as limits_service
from app.modules.limits.exceptions import LimitExceededError


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_reserve_agent_run_waits_for_global_capacity(monkeypatch) -> None:
    sessions: list[FakeSession] = []
    counts = iter([0, 8, 0, 7])
    created = SimpleNamespace(id=uuid4())

    def session_factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    async def no_op(*args, **kwargs) -> None:
        return None

    async def count_running(*args, **kwargs) -> int:
        return next(counts)

    async def create_run(*args, **kwargs):
        return created

    monkeypatch.setattr(capacity, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(capacity.limits_service, "lock_quota_capacity", no_op)
    monkeypatch.setattr(capacity.limits_service, "require_limit_available", no_op)
    monkeypatch.setattr(capacity.repository, "count_running_agent_runs", count_running)
    monkeypatch.setattr(capacity.repository, "create_agent_run", create_run)
    monkeypatch.setattr(capacity.asyncio, "sleep", no_op)

    result = await capacity.reserve_agent_run(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        triggered_by_id=uuid4(),
        previous_agent_run_id=None,
        trigger_type="chat",
        settings=Settings(
            hosted_cloud_mode=True,
            hosted_cloud_global_concurrent_agent_runs=8,
            hosted_cloud_agent_run_queue_wait_seconds=1,
            hosted_cloud_agent_run_queue_poll_seconds=0.01,
        ),
    )

    assert result is created
    assert len(sessions) == 2
    assert sessions[0].rollbacks == 1
    assert sessions[1].commits == 1


@pytest.mark.asyncio
async def test_reserve_agent_run_reports_organization_limit(monkeypatch) -> None:
    async def no_op(*args, **kwargs) -> None:
        return None

    async def count_running(*args, **kwargs) -> int:
        return 1

    async def organization_full(*args, **kwargs) -> None:
        raise LimitExceededError("full")

    monkeypatch.setattr(capacity, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(capacity.limits_service, "lock_quota_capacity", no_op)
    monkeypatch.setattr(
        capacity.limits_service,
        "require_limit_available",
        organization_full,
    )
    monkeypatch.setattr(capacity.repository, "count_running_agent_runs", count_running)

    with pytest.raises(
        LimitExceededError,
        match="agent_runs.concurrent.per_organization",
    ):
        await capacity.reserve_agent_run(
            organization_id=uuid4(),
            workspace_id=uuid4(),
            agent_id=uuid4(),
            conversation_id=None,
            triggered_by_id=uuid4(),
            previous_agent_run_id=None,
            trigger_type="chat",
            settings=Settings(
                hosted_cloud_mode=True,
                hosted_cloud_agent_run_queue_wait_seconds=0,
            ),
        )


@pytest.mark.asyncio
async def test_resume_rejects_when_global_capacity_is_full(monkeypatch) -> None:
    counts = iter([0, 8])

    async def no_op(*args, **kwargs) -> None:
        return None

    async def count_running(*args, **kwargs) -> int:
        return next(counts)

    monkeypatch.setattr(capacity.limits_service, "lock_quota_capacity", no_op)
    monkeypatch.setattr(capacity.limits_service, "require_limit_available", no_op)
    monkeypatch.setattr(capacity.repository, "count_running_agent_runs", count_running)

    with pytest.raises(AgentCapacityUnavailableError, match="capacity is busy"):
        await capacity.require_resume_capacity(
            FakeSession(),
            organization_id=uuid4(),
            settings=Settings(
                hosted_cloud_mode=True,
                hosted_cloud_global_concurrent_agent_runs=8,
            ),
        )


def test_hosted_cloud_defaults_match_launch_plan() -> None:
    settings = Settings(hosted_cloud_mode=True)

    assert limits_service.hosted_cloud_default_limit(
        settings, limits_service.MEMBERS_PER_ORGANIZATION
    ) == 1
    assert limits_service.hosted_cloud_default_limit(
        settings, limits_service.WORKSPACES_PER_ORGANIZATION
    ) == 1
    assert limits_service.hosted_cloud_default_limit(
        settings, limits_service.AGENTS_PER_ORGANIZATION
    ) == 3
    assert limits_service.hosted_cloud_default_limit(
        settings, limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION
    ) == 1
