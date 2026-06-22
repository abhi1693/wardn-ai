from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app import main


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_runtime_reaper(monkeypatch) -> None:
    task = object()
    seen = {}

    def get_settings():
        return SimpleNamespace(
            mcp_runtime_reaper_interval_seconds=11,
            mcp_runtime_reaper_batch_size=17,
            mcp_runtime_event_retention_days=21,
            mcp_runtime_invocation_retention_days=31,
        )

    def start_runtime_reaper(
        *,
        interval_seconds,
        limit,
        event_retention_days,
        invocation_retention_days,
    ):
        seen["start"] = {
            "interval_seconds": interval_seconds,
            "limit": limit,
            "event_retention_days": event_retention_days,
            "invocation_retention_days": invocation_retention_days,
        }
        return task

    async def stop_runtime_reaper(seen_task):
        seen["stop"] = seen_task

    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(main, "get_settings", get_settings)
    monkeypatch.setattr(main, "start_runtime_reaper", start_runtime_reaper)
    monkeypatch.setattr(main, "stop_runtime_reaper", stop_runtime_reaper)

    app = FastAPI()
    async with main.lifespan(app):
        assert app.state.mcp_runtime_reaper_task is task

    assert seen == {
        "start": {
            "interval_seconds": 11,
            "limit": 17,
            "event_retention_days": 21,
            "invocation_retention_days": 31,
        },
        "stop": task,
    }
