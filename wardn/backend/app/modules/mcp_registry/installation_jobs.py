import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.db.session import AsyncSessionLocal
from app.modules.limits import service as limits_service
from app.modules.limits.exceptions import LimitExceededError
from app.modules.mcp_registry import job_repository, repository, service
from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
    MCPServerNotFoundError,
)
from app.modules.mcp_registry.installer import default_install_root, server_install_path
from app.modules.mcp_registry.job_service import (
    enqueue_operation_job,
    job_response,
    operation_deduplication_key,
)
from app.modules.mcp_registry.job_worker import (
    JobProgressReporter,
    MCPJobCleanupError,
    MCPJobExecutionError,
)
from app.modules.mcp_registry.models import MCPOperationJob
from app.modules.mcp_registry.schemas import (
    MCPOperationJobRead,
    MCPServerBulkUpdateRequest,
    MCPServerInstallRequest,
)
from app.modules.users.models import User

INSTALL_SERVER_OPERATION = "install_server"
BULK_UPDATE_SERVERS_OPERATION = "update_installed_servers"


def workspace_installations_resource_key(workspace_id: uuid.UUID) -> str:
    return f"workspace:{workspace_id}:mcp-installations"


async def require_new_installation_capacity(
    session,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    installation_count = await repository.count_installations_for_workspace(
        session,
        workspace_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
        scope_chain=[("workspace", workspace_id), ("organization", organization_id)],
        current_count=installation_count,
    )


async def enqueue_server_installation(
    session,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user: User,
    server_name: str,
    payload: MCPServerInstallRequest,
) -> MCPOperationJobRead:
    resource_key = workspace_installations_resource_key(workspace_id)
    request_deduplication_key = operation_deduplication_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        operation=INSTALL_SERVER_OPERATION,
        resource_key=resource_key,
        request_payload={
            "serverName": server_name,
            "request": payload.model_dump(mode="json", by_alias=True),
        },
    )
    existing_job = await job_repository.get_active_job_by_deduplication_key(
        session,
        request_deduplication_key,
    )
    if existing_job is not None:
        events = await job_repository.list_job_events(session, existing_job.id)
        return job_response(existing_job, events)

    server = await repository.get_server_version(
        session,
        server_name,
        payload.version,
        include_deleted=False,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")
    installation = await repository.get_installation(
        session,
        server_name,
        payload.config_name,
        workspace_id,
    )
    if installation is None:
        await require_new_installation_capacity(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    config_values = service.merged_install_config_values(
        installation,
        payload.config_values,
    )
    config_values = await service.externalize_install_config_secrets(
        session,
        user,
        organization_id,
        workspace_id,
        server,
        payload,
        config_values,
    )
    desired_state = MCPServerInstallRequest(
        version=server.version,
        configName=payload.config_name,
        configValues=config_values,
        installTarget=payload.install_target,
    ).model_dump(mode="json", by_alias=True)
    return await enqueue_operation_job(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        requested_by_id=user.id,
        operation=INSTALL_SERVER_OPERATION,
        resource_key=resource_key,
        request_payload={"serverName": server_name, "desiredState": desired_state},
        progress_total=4,
        deduplication_key=request_deduplication_key,
    )


async def enqueue_installed_server_updates(
    session,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user: User,
    payload: MCPServerBulkUpdateRequest,
) -> MCPOperationJobRead:
    targets: list[dict[str, Any]] = []
    for server_name in sorted(set(payload.server_names)):
        installations = await repository.list_installations_for_server(
            session,
            server_name,
            workspace_id,
        )
        if not installations:
            raise MCPServerInstallationNotFoundError(f"server is not installed: {server_name}")
        latest = await repository.get_server_version(
            session,
            server_name,
            "latest",
            include_deleted=False,
            organization_id=organization_id,
        )
        if latest is None:
            raise MCPServerNotFoundError(f"latest server version not found: {server_name}")
        for installation in installations:
            install_target = "remote" if installation.install_type == "remote" else "package"
            config_values = service.install_config_values_from_secret_references(
                installation.secret_references
            )
            desired_state = MCPServerInstallRequest(
                version=latest.version,
                configName=installation.config_name,
                configValues=config_values,
                installTarget=install_target,
            ).model_dump(mode="json", by_alias=True)
            targets.append({"serverName": server_name, "desiredState": desired_state})

    return await enqueue_operation_job(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        requested_by_id=user.id,
        operation=BULK_UPDATE_SERVERS_OPERATION,
        resource_key=workspace_installations_resource_key(workspace_id),
        request_payload={"targets": targets},
        progress_total=max(1, len(targets) * 3),
    )


def cleanup_payload_for_server(
    *,
    workspace_id: uuid.UUID,
    server,
    config_name: str,
) -> dict[str, Any]:
    install_path = server_install_path(
        server,
        config_name=config_name,
        workspace_id=str(workspace_id),
    )
    return {
        "paths": [
            str(install_path.with_name(f"{install_path.name}.tmp")),
            str(install_path.with_name(f"{install_path.name}.backup")),
        ]
    }


def classify_installation_error(exc: Exception) -> MCPJobExecutionError:
    if isinstance(
        exc,
        (
            LimitExceededError,
            MCPServerInstallationNotFoundError,
            MCPServerInstallationUnsupportedError,
            MCPServerNotFoundError,
            ValueError,
        ),
    ):
        return MCPJobExecutionError(
            str(exc),
            code="invalid_installation_request",
            retryable=False,
        )
    if isinstance(exc, MCPServerInstallationFailedError):
        return MCPJobExecutionError(str(exc), code="installation_failed", retryable=True)
    return MCPJobExecutionError(str(exc), code="installation_failed", retryable=True)


async def execute_installation_target(
    job: MCPOperationJob,
    reporter: JobProgressReporter,
    *,
    server_name: str,
    desired_state: dict[str, Any],
    progress_start: int,
    progress_total: int,
) -> dict[str, Any]:
    if job.workspace_id is None:
        raise MCPJobExecutionError(
            "Installation job has no workspace",
            code="invalid_installation_request",
            retryable=False,
        )
    payload = MCPServerInstallRequest.model_validate(desired_state)
    await reporter.update(
        progress_start,
        progress_total,
        f"Preparing {server_name}",
        details={"serverName": server_name, "phase": "prepare"},
    )
    try:
        async with AsyncSessionLocal() as session:
            server = await repository.get_server_version(
                session,
                server_name,
                payload.version,
                include_deleted=False,
                organization_id=job.organization_id,
            )
            if server is None:
                raise MCPServerNotFoundError("server version not found")
            await reporter.register_cleanup(
                cleanup_payload_for_server(
                    workspace_id=job.workspace_id,
                    server=server,
                    config_name=payload.config_name,
                )
            )
            await reporter.update(
                progress_start + 1,
                progress_total,
                f"Installing {server_name}",
                details={"serverName": server_name, "phase": "install"},
            )
            installation = await service.install_server_version(
                session,
                server_name,
                payload,
                job.workspace_id,
                user=None,
            )
            await session.commit()
    except MCPJobExecutionError:
        raise
    except Exception as exc:
        raise classify_installation_error(exc) from exc

    await reporter.register_cleanup({})
    await reporter.update(
        progress_start + 2,
        progress_total,
        f"Installed {server_name}",
        details={"serverName": server_name, "phase": "complete"},
    )
    return installation.model_dump(mode="json", by_alias=True)


async def execute_server_installation(
    job: MCPOperationJob,
    reporter: JobProgressReporter,
) -> dict[str, Any]:
    server_name = str(job.request_payload.get("serverName") or "")
    desired_state = job.request_payload.get("desiredState")
    if not server_name or not isinstance(desired_state, dict):
        raise MCPJobExecutionError(
            "Installation job payload is invalid",
            code="invalid_installation_request",
            retryable=False,
        )
    installation = await execute_installation_target(
        job,
        reporter,
        server_name=server_name,
        desired_state=desired_state,
        progress_start=1,
        progress_total=4,
    )
    return {"installation": installation}


async def execute_installed_server_updates(
    job: MCPOperationJob,
    reporter: JobProgressReporter,
) -> dict[str, Any]:
    targets = job.request_payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise MCPJobExecutionError(
            "Bulk installation job payload is invalid",
            code="invalid_installation_request",
            retryable=False,
        )
    installations: list[dict[str, Any]] = []
    total = len(targets) * 3
    for index, target in enumerate(targets):
        if not isinstance(target, dict) or not isinstance(target.get("desiredState"), dict):
            raise MCPJobExecutionError(
                "Bulk installation target is invalid",
                code="invalid_installation_request",
                retryable=False,
            )
        server_name = str(target.get("serverName") or "")
        installation = await execute_installation_target(
            job,
            reporter,
            server_name=server_name,
            desired_state=target["desiredState"],
            progress_start=index * 3 + 1,
            progress_total=total,
        )
        installations.append(installation)
    return {"installations": installations}


def remove_retryable_install_paths(payload: dict[str, Any]) -> None:
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise MCPJobCleanupError("Installation cleanup payload is invalid", retryable=False)
    root = default_install_root().resolve()
    for raw_path in paths:
        if not isinstance(raw_path, str):
            raise MCPJobCleanupError("Installation cleanup path is invalid", retryable=False)
        path = Path(raw_path).absolute()
        if path.name.endswith((".tmp", ".backup")) is False or not path.is_relative_to(root):
            raise MCPJobCleanupError(
                "Installation cleanup path is outside the managed install root",
                retryable=False,
            )
        if path.is_symlink():
            path.unlink()
            continue
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise MCPJobCleanupError(
                "Installation cleanup path resolves outside the managed install root",
                retryable=False,
            )
        if path.exists():
            shutil.rmtree(path)


async def cleanup_server_installation(
    job: MCPOperationJob,
    payload: dict[str, Any],
) -> None:
    await asyncio.to_thread(remove_retryable_install_paths, payload)
