import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.modules.mcp_registry import repository as registry_repository
from app.modules.mcp_runtime.manager import (
    RUNTIME_KIND_PACKAGE,
    RUNTIME_PROVIDER_KUBERNETES,
    MCPRuntimeManager,
    get_runtime_manager,
    runtime_kind,
)
from app.modules.mcp_runtime.service import MCPRuntimeWarmupResult, warm_runtime_session

logger = logging.getLogger(__name__)


async def list_warmup_installation_ids(*, session_factory=AsyncSessionLocal) -> list[UUID]:
    async with session_factory() as session:
        installations = await registry_repository.list_installations(session)
        return [
            installation.id
            for installation in installations
            if installation.id is not None
            and installation.status == "enabled"
            and runtime_kind(installation) == RUNTIME_KIND_PACKAGE
        ]


async def warm_runtime_installation(
    installation_id: UUID,
    *,
    session_factory=AsyncSessionLocal,
    manager: MCPRuntimeManager | None = None,
) -> bool:
    runtime_manager = manager or get_runtime_manager()
    async with session_factory() as session:
        installation = await registry_repository.get_installation_by_id(session, installation_id)
        if (
            installation is None
            or installation.status != "enabled"
            or runtime_kind(installation) != RUNTIME_KIND_PACKAGE
        ):
            return False
        await warm_runtime_session(
            session,
            installation,
            manager=runtime_manager,
            wait_ready=False,
        )
        await session.commit()
        return True


async def run_runtime_warmup_once(
    *,
    session_factory=AsyncSessionLocal,
    manager: MCPRuntimeManager | None = None,
    concurrency: int | None = None,
) -> MCPRuntimeWarmupResult:
    settings = get_settings()
    if not settings.mcp_runtime_warm_on_startup:
        logger.info("MCP runtime startup warmup disabled.")
        return MCPRuntimeWarmupResult()
    if settings.mcp_runtime_provider.lower() != RUNTIME_PROVIDER_KUBERNETES:
        logger.info(
            "MCP runtime startup warmup skipped for provider %s.",
            settings.mcp_runtime_provider,
        )
        return MCPRuntimeWarmupResult()

    installation_ids = await list_warmup_installation_ids(session_factory=session_factory)
    if not installation_ids:
        return MCPRuntimeWarmupResult()

    limit = max(1, concurrency or settings.mcp_runtime_warm_startup_concurrency)
    semaphore = asyncio.Semaphore(limit)
    warmed_count = 0
    skipped_count = 0
    failed_count = 0

    async def warm_one(installation_id: UUID) -> bool:
        async with semaphore:
            return await warm_runtime_installation(
                installation_id,
                session_factory=session_factory,
                manager=manager,
            )

    results = await asyncio.gather(
        *(warm_one(installation_id) for installation_id in installation_ids),
        return_exceptions=True,
    )
    for installation_id, result in zip(installation_ids, results, strict=True):
        if isinstance(result, Exception):
            failed_count += 1
            logger.error(
                "MCP runtime startup warmup failed for installation %s.",
                installation_id,
                exc_info=(type(result), result, result.__traceback__),
            )
        elif result:
            warmed_count += 1
        else:
            skipped_count += 1

    logger.info(
        "MCP runtime startup warmup complete: warmed=%s skipped=%s failed=%s.",
        warmed_count,
        skipped_count,
        failed_count,
    )
    return MCPRuntimeWarmupResult(
        warmed_count=warmed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )


def start_runtime_warmup(
    *,
    session_factory=AsyncSessionLocal,
    manager: MCPRuntimeManager | None = None,
    concurrency: int | None = None,
    warm_once: Callable[..., Awaitable[MCPRuntimeWarmupResult]] = run_runtime_warmup_once,
) -> asyncio.Task[MCPRuntimeWarmupResult] | None:
    settings = get_settings()
    if (
        not settings.mcp_runtime_warm_on_startup
        or settings.mcp_runtime_provider.lower() != RUNTIME_PROVIDER_KUBERNETES
    ):
        return None
    logger.info("Starting MCP runtime startup warmup.")
    return asyncio.create_task(
        warm_once(
            session_factory=session_factory,
            manager=manager,
            concurrency=concurrency,
        ),
        name="mcp-runtime-warmup",
    )


async def stop_runtime_warmup(task: asyncio.Task[MCPRuntimeWarmupResult] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
