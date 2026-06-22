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

    result = await warmup.run_runtime_warmup_once()

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

    result = await warmup.run_runtime_warmup_once()

    assert seen == [first_installation_id, second_installation_id]
    assert result.warmed_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 0
