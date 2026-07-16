from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app import main


@pytest.mark.asyncio
async def test_lifespan_only_tears_down_process_local_runtimes(monkeypatch) -> None:
    seen = {}

    async def teardown_local_runtime_processes():
        seen["local_teardown"] = True

    async def dispose_engine():
        seen["engine_disposed"] = True

    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(
        main,
        "teardown_local_runtime_processes",
        teardown_local_runtime_processes,
    )
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=dispose_engine))

    app = FastAPI()
    async with main.lifespan(app):
        assert not hasattr(app.state, "mcp_runtime_reaper_task")
        assert not hasattr(app.state, "mcp_runtime_warmup_task")

    assert seen == {
        "local_teardown": True,
        "engine_disposed": True,
    }
