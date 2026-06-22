import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.modules.mcp_runtime.service import (
    MCPRuntimeReapResult,
    prune_runtime_events,
    prune_tool_invocations,
    reap_expired_runtime_sessions,
)

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


async def run_runtime_reaper_once(
    *,
    session_factory=AsyncSessionLocal,
    limit: int = 100,
    event_retention_days: int | None = None,
    invocation_retention_days: int | None = None,
) -> MCPRuntimeReapResult:
    settings = get_settings()
    event_retention_days = (
        settings.mcp_runtime_event_retention_days
        if event_retention_days is None
        else event_retention_days
    )
    invocation_retention_days = (
        settings.mcp_runtime_invocation_retention_days
        if invocation_retention_days is None
        else invocation_retention_days
    )
    async with session_factory() as session:
        reap_result = await reap_expired_runtime_sessions(session, limit=limit)
        deleted_event_count = await prune_runtime_events(
            session,
            retention_days=event_retention_days,
        )
        deleted_invocation_count = await prune_tool_invocations(
            session,
            retention_days=invocation_retention_days,
        )
        await session.commit()

    result = MCPRuntimeReapResult(
        stopped_count=reap_result.stopped_count,
        deleted_event_count=deleted_event_count,
        deleted_invocation_count=deleted_invocation_count,
    )
    if result.stopped_count or result.deleted_event_count or result.deleted_invocation_count:
        logger.info("MCP runtime reaper stopped %s expired sessions.", result.stopped_count)
        logger.info("MCP runtime reaper deleted %s expired events.", result.deleted_event_count)
        logger.info(
            "MCP runtime reaper deleted %s expired tool invocations.",
            result.deleted_invocation_count,
        )
    return result


async def run_runtime_reaper_loop(
    *,
    interval_seconds: int,
    limit: int = 100,
    event_retention_days: int | None = None,
    invocation_retention_days: int | None = None,
    session_factory=AsyncSessionLocal,
    sleep: Sleep = asyncio.sleep,
    reap_once: Callable[..., Awaitable[MCPRuntimeReapResult]] = run_runtime_reaper_once,
) -> None:
    if interval_seconds < 1:
        logger.info("MCP runtime reaper disabled.")
        return

    while True:
        try:
            await reap_once(
                session_factory=session_factory,
                limit=limit,
                event_retention_days=event_retention_days,
                invocation_retention_days=invocation_retention_days,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP runtime reaper iteration failed.")

        await sleep(interval_seconds)


def start_runtime_reaper(
    *,
    interval_seconds: int,
    limit: int = 100,
    event_retention_days: int | None = None,
    invocation_retention_days: int | None = None,
    session_factory=AsyncSessionLocal,
) -> asyncio.Task[None] | None:
    if interval_seconds < 1:
        return None
    logger.info(
        "Starting MCP runtime reaper with %s second interval and batch size %s.",
        interval_seconds,
        limit,
    )
    return asyncio.create_task(
        run_runtime_reaper_loop(
            interval_seconds=interval_seconds,
            limit=limit,
            event_retention_days=event_retention_days,
            invocation_retention_days=invocation_retention_days,
            session_factory=session_factory,
        ),
        name="mcp-runtime-reaper",
    )


async def stop_runtime_reaper(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
