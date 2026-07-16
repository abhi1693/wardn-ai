from app.modules.mcp_registry.installation_jobs import (
    BULK_UPDATE_SERVERS_OPERATION,
    INSTALL_SERVER_OPERATION,
    cleanup_server_installation,
    execute_installed_server_updates,
    execute_server_installation,
)
from app.modules.mcp_registry.job_worker import MCPJobHandlers


def build_job_handlers() -> MCPJobHandlers:
    return MCPJobHandlers(
        executors={
            INSTALL_SERVER_OPERATION: execute_server_installation,
            BULK_UPDATE_SERVERS_OPERATION: execute_installed_server_updates,
        },
        cleanup_executors={
            INSTALL_SERVER_OPERATION: cleanup_server_installation,
            BULK_UPDATE_SERVERS_OPERATION: cleanup_server_installation,
        },
    )
