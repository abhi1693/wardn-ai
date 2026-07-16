import uuid
from types import SimpleNamespace

import pytest

from app.modules.mcp_runtime import warmup


@pytest.mark.asyncio
async def test_runtime_warmup_skips_when_provider_is_not_kubernetes(monkeypatch) -> None:
    monkeypatch.setattr(
        warmup,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_runtime_warm_on_startup=True,
            mcp_runtime_provider="local",
            mcp_runtime_warm_startup_concurrency=4,
        ),
    )

    async def list_warmup_installation_ids(**kwargs):
        raise AssertionError("warmup should not query installations")

    monkeypatch.setattr(
        warmup,
        "list_warmup_installation_ids",
        list_warmup_installation_ids,
    )

    result = await warmup.run_runtime_warmup_once(acquire_leadership=False)

    assert result.warmed_count == 0
    assert result.skipped_count == 0
    assert result.failed_count == 0


@pytest.mark.asyncio
async def test_runtime_warmup_warms_enabled_package_installations(monkeypatch) -> None:
    first_installation_id = uuid.uuid4()
    second_installation_id = uuid.uuid4()
    seen = []
    monkeypatch.setattr(
        warmup,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_runtime_warm_on_startup=True,
            mcp_runtime_provider="kubernetes",
            mcp_runtime_warm_startup_concurrency=2,
        ),
    )

    async def list_warmup_installation_ids(**kwargs):
        return [first_installation_id, second_installation_id]

    async def warm_runtime_installation(installation_id, **kwargs):
        seen.append(installation_id)
        return installation_id == first_installation_id

    monkeypatch.setattr(
        warmup,
        "list_warmup_installation_ids",
        list_warmup_installation_ids,
    )
    monkeypatch.setattr(
        warmup,
        "warm_runtime_installation",
        warm_runtime_installation,
    )

    result = await warmup.run_runtime_warmup_once(acquire_leadership=False)

    assert seen == [first_installation_id, second_installation_id]
    assert result.warmed_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 0


@pytest.mark.asyncio
async def test_runtime_warmup_skips_when_another_worker_owns_maintenance(monkeypatch) -> None:
    class FakeSession:
        rolled_back = False

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

    monkeypatch.setattr(
        warmup,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_runtime_warm_on_startup=True,
            mcp_runtime_provider="kubernetes",
            mcp_runtime_warm_startup_concurrency=2,
        ),
    )

    async def lock_not_acquired(session, lock_id):
        return False

    async def fail_list(**kwargs):
        raise AssertionError("warmup should not run without maintenance leadership")

    session_factory = FakeSessionFactory()
    monkeypatch.setattr(warmup, "try_advisory_transaction_lock", lock_not_acquired)
    monkeypatch.setattr(warmup, "list_warmup_installation_ids", fail_list)

    result = await warmup.run_runtime_warmup_once(session_factory=session_factory)

    assert result.warmed_count == 0
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert session_factory.session.rolled_back is True
