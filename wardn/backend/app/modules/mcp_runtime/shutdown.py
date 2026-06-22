import logging

from app.db.session import AsyncSessionLocal
from app.modules.mcp_runtime.manager import MCPRuntimeManager
from app.modules.mcp_runtime.service import (
    MCPRuntimeShutdownResult,
    shutdown_active_runtime_sessions,
)

logger = logging.getLogger(__name__)


async def teardown_runtime_sessions(
    *,
    session_factory=AsyncSessionLocal,
    manager: MCPRuntimeManager | None = None,
    limit: int = 1000,
) -> MCPRuntimeShutdownResult:
    async with session_factory() as session:
        result = await shutdown_active_runtime_sessions(
            session,
            manager=manager,
            limit=limit,
        )
        await session.commit()

    if result.stopped_count or result.failed_count:
        logger.info(
            "MCP runtime shutdown teardown complete: stopped=%s failed=%s.",
            result.stopped_count,
            result.failed_count,
        )
    return result
