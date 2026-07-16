from starlette.concurrency import run_in_threadpool

from app.modules.mcp_runtime.manager import MCPRuntimeManager, get_runtime_manager


async def teardown_local_runtime_processes(
    *,
    manager: MCPRuntimeManager | None = None,
) -> None:
    runtime_manager = manager or get_runtime_manager()
    await run_in_threadpool(runtime_manager.shutdown_local_runtimes)
