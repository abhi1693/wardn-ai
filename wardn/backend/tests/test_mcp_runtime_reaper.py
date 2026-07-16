import asyncio

import pytest

from app.modules.mcp_runtime import reaper
from app.modules.mcp_runtime.service import MCPRuntimeReapResult


class FakeSession:
    committed = False
    rolled_back = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class FakeSessionFactory:
    def __init__(self):
        self.session = FakeSession()

    def __call__(self):
        return FakeSessionContext(self.session)


@pytest.mark.asyncio
async def test_run_runtime_reaper_once_reaps_and_commits(monkeypatch) -> None:
    seen = {}

    async def reap_expired_runtime_sessions(session, *, limit=100):
        seen["session"] = session
        seen["limit"] = limit
        return MCPRuntimeReapResult(stopped_count=2)

    async def prune_runtime_events(session, *, retention_days):
        seen["retention_session"] = session
        seen["retention_days"] = retention_days
        return 5

    async def prune_tool_invocations(session, *, retention_days):
        seen["invocation_retention_session"] = session
        seen["invocation_retention_days"] = retention_days
        return 8

    async def recover_stale_tool_invocations(session, *, stale_after_seconds, limit):
        seen["recovery_session"] = session
        seen["stale_after_seconds"] = stale_after_seconds
        seen["recovery_limit"] = limit
        return 3

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(
        reaper,
        "reap_expired_runtime_sessions",
        reap_expired_runtime_sessions,
    )
    monkeypatch.setattr(reaper, "prune_runtime_events", prune_runtime_events)
    monkeypatch.setattr(reaper, "prune_tool_invocations", prune_tool_invocations)
    monkeypatch.setattr(
        reaper,
        "recover_stale_tool_invocations",
        recover_stale_tool_invocations,
    )

    result = await reaper.run_runtime_reaper_once(
        session_factory=session_factory,
        limit=25,
        event_retention_days=9,
        invocation_retention_days=30,
        acquire_leadership=False,
    )

    assert result.stopped_count == 2
    assert result.deleted_event_count == 5
    assert result.deleted_invocation_count == 8
    assert result.recovered_invocation_count == 3
    assert seen == {
        "session": session_factory.session,
        "limit": 25,
        "retention_session": session_factory.session,
        "retention_days": 9,
        "invocation_retention_session": session_factory.session,
        "invocation_retention_days": 30,
        "recovery_session": session_factory.session,
        "stale_after_seconds": reaper.get_settings().mcp_runtime_invocation_stale_seconds,
        "recovery_limit": 25,
    }
    assert session_factory.session.committed is True


@pytest.mark.asyncio
async def test_runtime_reaper_skips_when_another_worker_owns_maintenance(monkeypatch) -> None:
    async def lock_not_acquired(session, lock_id):
        return False

    async def fail_reap(*args, **kwargs):
        raise AssertionError("reaper should not run without maintenance leadership")

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(reaper, "try_advisory_transaction_lock", lock_not_acquired)
    monkeypatch.setattr(reaper, "reap_expired_runtime_sessions", fail_reap)

    result = await reaper.run_runtime_reaper_once(session_factory=session_factory)

    assert result.stopped_count == 0
    assert result.deleted_event_count == 0
    assert result.deleted_invocation_count == 0
    assert session_factory.session.rolled_back is True


@pytest.mark.asyncio
async def test_runtime_reaper_loop_sleeps_after_iteration_failure() -> None:
    seen = {}

    async def failing_reap_once(**kwargs):
        seen["reap_kwargs"] = kwargs
        raise RuntimeError("database unavailable")

    async def cancelling_sleep(interval):
        seen["interval"] = interval
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await reaper.run_runtime_reaper_loop(
            interval_seconds=7,
            limit=13,
            event_retention_days=3,
            invocation_retention_days=17,
            session_factory="factory",
            sleep=cancelling_sleep,
            reap_once=failing_reap_once,
        )

    assert seen == {
        "reap_kwargs": {
            "session_factory": "factory",
            "limit": 13,
            "event_retention_days": 3,
            "invocation_retention_days": 17,
        },
        "interval": 7,
    }


@pytest.mark.asyncio
async def test_runtime_reaper_loop_can_be_disabled() -> None:
    async def failing_reap_once(**kwargs):
        raise AssertionError("disabled reaper should not run")

    await reaper.run_runtime_reaper_loop(
        interval_seconds=0,
        reap_once=failing_reap_once,
    )


@pytest.mark.asyncio
async def test_stop_runtime_reaper_cancels_task() -> None:
    async def wait_forever():
        await asyncio.Event().wait()

    task = asyncio.create_task(wait_forever())

    await reaper.stop_runtime_reaper(task)

    assert task.cancelled()
