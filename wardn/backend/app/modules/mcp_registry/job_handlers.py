from app.modules.mcp_registry.job_worker import MCPJobHandlers


def build_job_handlers() -> MCPJobHandlers:
    return MCPJobHandlers(executors={}, cleanup_executors={})
