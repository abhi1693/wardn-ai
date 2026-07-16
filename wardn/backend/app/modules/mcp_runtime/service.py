import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_runtime import repository
from app.modules.mcp_runtime.exceptions import MCPRuntimeSessionNotFoundError
from app.modules.mcp_runtime.manager import (
    MCPRuntimeManager,
    get_runtime_manager,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession, MCPToolInvocation
from app.modules.mcp_runtime.schemas import (
    MCPRuntimeEventListResponse,
    MCPRuntimeEventRead,
    MCPRuntimeServerError,
    MCPRuntimeSessionHealthResponse,
    MCPRuntimeSessionListResponse,
    MCPRuntimeSessionRead,
    MCPRuntimeSummaryResponse,
    MCPRuntimeToolCallSummary,
)
from app.modules.organizations import repository as organization_repository
from app.modules.secrets.exceptions import SecretsError
from app.modules.secrets.service import resolve_secret

logger = logging.getLogger(__name__)

RUNTIME_EVENT_SESSION_CREATED = "runtime_session_created"
RUNTIME_EVENT_SESSION_REUSED = "runtime_session_reused"
RUNTIME_EVENT_SESSION_REPLACED = "runtime_session_replaced"
RUNTIME_EVENT_WARMUP_STARTED = "runtime_warmup_started"
RUNTIME_EVENT_WARMUP_SUCCEEDED = "runtime_warmup_succeeded"
RUNTIME_EVENT_WARMUP_FAILED = "runtime_warmup_failed"
RUNTIME_EVENT_TOOL_CALL_STARTED = "tool_call_started"
RUNTIME_EVENT_TOOL_CALL_SUCCEEDED = "tool_call_succeeded"
RUNTIME_EVENT_TOOL_CALL_FAILED = "tool_call_failed"
RUNTIME_EVENT_SESSION_STOPPED = "runtime_session_stopped"
RUNTIME_EVENT_REAPER_STOPPED = "runtime_reaper_stopped"
RUNTIME_SUMMARY_RECENT_WINDOW = timedelta(hours=24)
SECRET_HANDLE_REF_TYPE = "secret_handle"
ACTIVE_RUNTIME_SESSION_CONSTRAINT = "uq_mcp_runtime_sessions_one_active_per_installation"


@dataclass(frozen=True)
class MCPRuntimeReapResult:
    stopped_count: int
    deleted_event_count: int = 0
    deleted_invocation_count: int = 0
    recovered_invocation_count: int = 0


@dataclass(frozen=True)
class MCPRuntimeWarmupResult:
    warmed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True)
class PreparedMCPToolCall:
    installation: Any
    runtime_session: MCPRuntimeSession
    invocation: MCPToolInvocation
    invocation_id: UUID
    deferred_runtime_stops: tuple[MCPRuntimeSession, ...] = ()


def runtime_session_read(runtime_session: MCPRuntimeSession) -> MCPRuntimeSessionRead:
    return MCPRuntimeSessionRead(
        id=runtime_session.id,
        organizationId=runtime_session.organization_id,
        workspaceId=runtime_session.workspace_id,
        installationId=runtime_session.installation_id,
        serverName=runtime_session.server_name,
        serverVersion=runtime_session.server_version,
        runtimeProvider=runtime_session.runtime_provider,
        runtimeKind=runtime_session.runtime_kind,
        status=runtime_session.status,
        podName=runtime_session.pod_name,
        namespace=runtime_session.namespace,
        startedAt=runtime_session.started_at,
        readyAt=runtime_session.ready_at,
        lastUsedAt=runtime_session.last_used_at,
        expiresAt=runtime_session.expires_at,
        stoppedAt=runtime_session.stopped_at,
        failureCount=runtime_session.failure_count,
        lastError=runtime_session.last_error,
    )


def runtime_event_read(runtime_event) -> MCPRuntimeEventRead:
    return MCPRuntimeEventRead(
        id=runtime_event.id,
        runtimeSessionId=runtime_event.runtime_session_id,
        eventType=runtime_event.event_type,
        message=runtime_event.message,
        metadata=runtime_event.event_metadata,
        createdAt=runtime_event.created_at,
    )


def runtime_server_error_read(runtime_session: MCPRuntimeSession) -> MCPRuntimeServerError:
    return MCPRuntimeServerError(
        serverName=runtime_session.server_name,
        serverVersion=runtime_session.server_version,
        lastError=runtime_session.last_error,
        lastErrorAt=runtime_session.updated_at,
        failureCount=runtime_session.failure_count,
    )


def summarize_tool_call_counts(
    counts: list[tuple[str, bool, int]],
) -> tuple[int, int, int, int]:
    total = 0
    succeeded = 0
    failed = 0
    running = 0
    for status, is_error, count in counts:
        total += count
        if status == "running":
            running += count
        elif status == "failed" or is_error:
            failed += count
        elif status == "succeeded":
            succeeded += count
    return total, succeeded, failed, running


def add_runtime_event(
    session: AsyncSession,
    runtime_session: MCPRuntimeSession,
    event_type: str,
    *,
    message: str = "",
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    session.add(
        repository.create_runtime_event(
            runtime_session_id=runtime_session.id,
            event_type=event_type,
            message=message,
            metadata=metadata,
            now=now,
        )
    )


def is_active_runtime_session_conflict(exc: IntegrityError) -> bool:
    return ACTIVE_RUNTIME_SESSION_CONSTRAINT in str(exc)


async def reuse_conflicting_runtime_session(
    session: AsyncSession,
    *,
    installation_id: UUID,
    config_fingerprint: str,
    expires_at: datetime,
    now: datetime,
) -> MCPRuntimeSession | None:
    existing = await repository.get_active_runtime_session(
        session,
        installation_id,
        now=now,
    )
    if existing is None or existing.config_fingerprint != config_fingerprint:
        return None

    existing.status = "running"
    existing.last_used_at = now
    existing.expires_at = expires_at
    existing.last_error = ""
    add_runtime_event(
        session,
        existing,
        RUNTIME_EVENT_SESSION_REUSED,
        message="Runtime session reused after concurrent creation.",
        metadata={"status": existing.status, "reason": "concurrent_create"},
        now=now,
    )
    await session.flush()
    return existing


def payload_size_bytes(payload: Any) -> int:
    try:
        return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except TypeError:
        return 0


def runtime_expires_at(now: datetime | None = None) -> datetime:
    settings = get_settings()
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=settings.mcp_runtime_idle_timeout_seconds)


def secret_handle_ref_id(value: Any) -> UUID | None:
    if not isinstance(value, dict) or value.get("type") != SECRET_HANDLE_REF_TYPE:
        return None
    raw_handle_id = value.get("secretHandleId") or value.get("secret_handle_id")
    if not raw_handle_id:
        return None
    return UUID(str(raw_handle_id))


def has_secret_handle_refs(value: Any) -> bool:
    if secret_handle_ref_id(value) is not None:
        return True
    if isinstance(value, dict):
        return any(has_secret_handle_refs(item) for item in value.values())
    if isinstance(value, list):
        return any(has_secret_handle_refs(item) for item in value)
    return False


async def organization_id_for_workspace(
    session: AsyncSession,
    workspace_id: UUID | None,
) -> UUID | None:
    if workspace_id is None:
        return None
    workspace = await organization_repository.get_workspace_by_id(session, workspace_id)
    return workspace.organization_id if workspace else None


async def materialize_secret_value(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    value: Any,
) -> Any:
    handle_id = secret_handle_ref_id(value)
    if handle_id is None:
        return value
    try:
        resolved = await resolve_secret(
            session,
            organization_id,
            handle_id,
            workspace_id=workspace_id,
        )
    except SecretsError as exc:
        raise ValueError(str(exc)) from exc
    return resolved.value


async def materialize_installation_secret_references(
    session: AsyncSession,
    installation: MCPServerInstallation,
) -> Any:
    secret_references = installation.secret_references or {}
    if not has_secret_handle_refs(secret_references):
        return installation
    organization_id = await organization_id_for_workspace(session, installation.workspace_id)
    if organization_id is None:
        raise ValueError("installation workspace organization is not available")

    materialized = deepcopy(secret_references)
    for namespace in ("headers", "environment", "packageArguments"):
        namespace_values = materialized.get(namespace)
        if not isinstance(namespace_values, dict):
            continue
        for key, value in list(namespace_values.items()):
            namespace_values[key] = await materialize_secret_value(
                session,
                organization_id=organization_id,
                workspace_id=installation.workspace_id,
                value=value,
            )
    files = materialized.get("files")
    if isinstance(files, dict):
        for detail in files.values():
            if not isinstance(detail, dict):
                continue
            detail["content"] = await materialize_secret_value(
                session,
                organization_id=organization_id,
                workspace_id=installation.workspace_id,
                value=detail.get("content"),
            )

    return SimpleNamespace(
        id=installation.id,
        workspace_id=installation.workspace_id,
        server_name=installation.server_name,
        config_name=installation.config_name,
        installed_version=installation.installed_version,
        status=installation.status,
        install_type=installation.install_type,
        install_path=installation.install_path,
        runtime_config=installation.runtime_config,
        secret_references=materialized,
        install_error=installation.install_error,
        installed_at=installation.installed_at,
        created_at=installation.created_at,
        updated_at=installation.updated_at,
    )


async def ensure_runtime_session(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    manager: MCPRuntimeManager,
    now: datetime | None = None,
    deferred_runtime_stops: list[MCPRuntimeSession] | None = None,
) -> MCPRuntimeSession:
    installation = await materialize_installation_secret_references(session, installation)
    now = now or datetime.now(UTC)
    organization_id = await organization_id_for_workspace(session, installation.workspace_id)
    runtime_spec = manager.runtime_spec(installation)
    config_fingerprint = runtime_spec.fingerprint()
    existing = await repository.get_active_runtime_session(
        session,
        installation.id,
        now=now,
    )
    expires_at = runtime_expires_at(now)
    if existing is not None:
        if (
            existing.config_fingerprint != config_fingerprint
            or existing.expires_at is not None
            and existing.expires_at <= now
        ):
            reason = (
                "config_fingerprint_changed"
                if existing.config_fingerprint != config_fingerprint
                else "expired"
            )
            if deferred_runtime_stops is None:
                await run_in_threadpool(manager.stop_runtime, existing)
            else:
                deferred_runtime_stops.append(existing)
            existing.status = "stopped"
            existing.stopped_at = now
            add_runtime_event(
                session,
                existing,
                RUNTIME_EVENT_SESSION_REPLACED,
                message="Runtime session replaced.",
                metadata={"reason": reason},
                now=now,
            )
            await session.flush()
        else:
            if existing.organization_id is None:
                existing.organization_id = organization_id
            existing.status = "running"
            existing.last_used_at = now
            existing.expires_at = expires_at
            existing.last_error = ""
            add_runtime_event(
                session,
                existing,
                RUNTIME_EVENT_SESSION_REUSED,
                message="Runtime session reused.",
                metadata={"status": existing.status},
                now=now,
            )
            await session.flush()
            return existing

    runtime_session = repository.create_runtime_session(
        installation_id=installation.id,
        organization_id=organization_id,
        workspace_id=installation.workspace_id,
        server_name=server.name,
        server_version=server.version,
        runtime_provider=runtime_spec.provider_name,
        runtime_kind=runtime_spec.runtime_kind,
        config_fingerprint=config_fingerprint,
        namespace=get_settings().mcp_runtime_namespace,
        endpoint_url=runtime_spec.endpoint_url,
        now=now,
        expires_at=expires_at,
    )
    try:
        async with session.begin_nested():
            session.add(runtime_session)
            await session.flush()
    except IntegrityError as exc:
        if not is_active_runtime_session_conflict(exc):
            raise
        existing = await reuse_conflicting_runtime_session(
            session,
            installation_id=installation.id,
            config_fingerprint=config_fingerprint,
            expires_at=expires_at,
            now=now,
        )
        if existing is None:
            raise
        return existing
    add_runtime_event(
        session,
        runtime_session,
        RUNTIME_EVENT_SESSION_CREATED,
        message="Runtime session created.",
        metadata={
            "runtimeProvider": runtime_session.runtime_provider,
            "runtimeKind": runtime_session.runtime_kind,
        },
        now=now,
    )
    await session.flush()
    return runtime_session


async def warm_runtime_session(
    session: AsyncSession,
    installation: MCPServerInstallation,
    *,
    manager: MCPRuntimeManager | None = None,
    now: datetime | None = None,
    wait_ready: bool = True,
) -> MCPRuntimeSession:
    manager = manager or get_runtime_manager()
    runtime_installation = await materialize_installation_secret_references(
        session,
        installation,
    )
    now = now or datetime.now(UTC)
    server = MCPServerVersion(
        name=installation.server_name,
        version=installation.installed_version,
    )
    deferred_runtime_stops: list[MCPRuntimeSession] = []
    runtime_session = await ensure_runtime_session(
        session,
        runtime_installation,
        server,
        manager=manager,
        now=now,
        deferred_runtime_stops=deferred_runtime_stops,
    )
    runtime_session.status = "running"
    runtime_session.last_error = ""
    add_runtime_event(
        session,
        runtime_session,
        RUNTIME_EVENT_WARMUP_STARTED,
        message="Runtime warmup started.",
        metadata={"runtimeProvider": runtime_session.runtime_provider},
        now=now,
    )
    await session.flush()
    await session.commit()

    try:
        for deferred_runtime_session in deferred_runtime_stops:
            await run_in_threadpool(manager.stop_runtime, deferred_runtime_session)
        health = await run_in_threadpool(
            manager.ensure_runtime,
            runtime_installation,
            runtime_session=runtime_session,
            wait_ready=wait_ready,
        )
    except Exception as exc:
        failed_at = datetime.now(UTC)
        runtime_session.status = "failed"
        runtime_session.failure_count += 1
        runtime_session.last_error = str(exc)
        runtime_session.last_used_at = failed_at
        add_runtime_event(
            session,
            runtime_session,
            RUNTIME_EVENT_WARMUP_FAILED,
            message="Runtime warmup failed.",
            metadata={"errorType": exc.__class__.__name__},
            now=failed_at,
        )
        await session.flush()
        raise

    ready_at = datetime.now(UTC)
    runtime_session.status = "idle"
    if health.ready:
        runtime_session.ready_at = ready_at
    elif runtime_session.ready_at == now:
        runtime_session.ready_at = None
    runtime_session.last_used_at = ready_at
    runtime_session.expires_at = runtime_expires_at(ready_at)
    runtime_session.last_error = ""
    add_runtime_event(
        session,
        runtime_session,
        RUNTIME_EVENT_WARMUP_SUCCEEDED,
        message="Runtime warmup succeeded.",
        metadata={
            "healthStatus": health.status,
            "ready": health.ready,
        },
        now=ready_at,
    )
    await session.flush()
    return runtime_session


def mark_invocation_success(
    runtime_session: MCPRuntimeSession,
    invocation,
    result: dict[str, Any],
    *,
    now: datetime,
) -> None:
    invocation.status = "succeeded"
    invocation.finished_at = now
    invocation.duration_ms = int((now - invocation.started_at).total_seconds() * 1000)
    invocation.output_size_bytes = payload_size_bytes(result)
    invocation.is_error = bool(result.get("isError"))
    invocation.error = ""
    runtime_session.status = "idle"
    runtime_session.last_used_at = now
    runtime_session.expires_at = runtime_expires_at(now)
    runtime_session.last_error = ""


def mark_invocation_failed(
    runtime_session: MCPRuntimeSession,
    invocation,
    error: BaseException,
    *,
    now: datetime,
) -> None:
    invocation.status = "failed"
    invocation.finished_at = now
    invocation.duration_ms = int((now - invocation.started_at).total_seconds() * 1000)
    invocation.output_size_bytes = 0
    invocation.is_error = True
    invocation.error = str(error)
    runtime_session.status = "idle"
    runtime_session.last_used_at = now
    runtime_session.expires_at = runtime_expires_at(now)
    runtime_session.failure_count += 1
    runtime_session.last_error = str(error)


async def prepare_tool_call_tracking(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    manager: MCPRuntimeManager | None = None,
    defer_runtime_stops: bool = False,
) -> PreparedMCPToolCall:
    manager = manager or get_runtime_manager()
    runtime_installation = await materialize_installation_secret_references(
        session,
        installation,
    )
    now = datetime.now(UTC)
    deferred_runtime_stops: list[MCPRuntimeSession] | None = [] if defer_runtime_stops else None
    runtime_session = await ensure_runtime_session(
        session,
        runtime_installation,
        server,
        manager=manager,
        now=now,
        deferred_runtime_stops=deferred_runtime_stops,
    )
    invocation = repository.create_tool_invocation(
        runtime_session=runtime_session,
        installation_id=installation.id,
        server_name=server.name,
        server_version=server.version,
        tool_name=tool_name,
        input_size_bytes=payload_size_bytes(arguments),
        user_id=user_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        now=now,
    )
    session.add(invocation)
    await session.flush()
    add_runtime_event(
        session,
        runtime_session,
        RUNTIME_EVENT_TOOL_CALL_STARTED,
        message="Tool call started.",
        metadata={
            "toolName": tool_name,
            "inputSizeBytes": invocation.input_size_bytes,
        },
        now=now,
    )
    await session.flush()

    if invocation.id is None:
        raise RuntimeError("tool invocation id was not generated")
    return PreparedMCPToolCall(
        installation=runtime_installation,
        runtime_session=runtime_session,
        invocation=invocation,
        invocation_id=invocation.id,
        deferred_runtime_stops=tuple(deferred_runtime_stops or ()),
    )


def execute_prepared_tool_call(
    prepared: PreparedMCPToolCall,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    cancel_event: Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    request_meta: dict[str, Any] | None = None,
    progress_callback=None,
    manager: MCPRuntimeManager | None = None,
) -> dict[str, Any]:
    manager = manager or get_runtime_manager()
    for runtime_session in prepared.deferred_runtime_stops:
        manager.stop_runtime(runtime_session)
    return manager.call_tool(
        prepared.installation,
        tool_name=tool_name,
        arguments=arguments,
        cancel_event=cancel_event,
        cancel_reason=cancel_reason,
        request_meta=request_meta,
        progress_callback=progress_callback,
        runtime_session=prepared.runtime_session,
    )


def detach_prepared_tool_call(session: AsyncSession, prepared: PreparedMCPToolCall) -> None:
    session.expunge(prepared.runtime_session)
    session.expunge(prepared.invocation)
    for runtime_session in prepared.deferred_runtime_stops:
        session.expunge(runtime_session)


async def finalize_prepared_tool_call(
    session: AsyncSession,
    prepared: PreparedMCPToolCall,
    *,
    tool_name: str,
    result: dict[str, Any] | None = None,
    error: BaseException | None = None,
    reload: bool = True,
) -> None:
    if reload:
        invocation = await repository.get_tool_invocation(
            session,
            prepared.invocation_id,
            for_update=True,
        )
        runtime_session_id = prepared.runtime_session.id
        if invocation is None or runtime_session_id is None:
            raise RuntimeError("prepared tool invocation no longer exists")
        runtime_session = await repository.get_runtime_session(
            session,
            runtime_session_id,
            for_update=True,
        )
        if runtime_session is None:
            raise RuntimeError("prepared runtime session no longer exists")
    else:
        invocation = prepared.invocation
        runtime_session = prepared.runtime_session

    runtime_session.namespace = prepared.runtime_session.namespace
    runtime_session.pod_name = prepared.runtime_session.pod_name
    runtime_session.endpoint_url = prepared.runtime_session.endpoint_url
    if error is not None:
        mark_invocation_failed(
            runtime_session,
            invocation,
            error,
            now=datetime.now(UTC),
        )
        add_runtime_event(
            session,
            runtime_session,
            RUNTIME_EVENT_TOOL_CALL_FAILED,
            message="Tool call failed.",
            metadata={
                "toolName": tool_name,
                "durationMs": invocation.duration_ms,
                "errorType": error.__class__.__name__,
            },
        )
    elif result is not None:
        mark_invocation_success(
            runtime_session,
            invocation,
            result,
            now=datetime.now(UTC),
        )
        add_runtime_event(
            session,
            runtime_session,
            RUNTIME_EVENT_TOOL_CALL_SUCCEEDED,
            message="Tool call succeeded.",
            metadata={
                "toolName": tool_name,
                "durationMs": invocation.duration_ms,
                "outputSizeBytes": invocation.output_size_bytes,
                "isError": invocation.is_error,
            },
        )
    else:
        raise ValueError("result or error is required to finalize a tool call")
    await session.flush()


async def call_tool_with_tracking(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    cancel_event: Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    request_meta: dict[str, Any] | None = None,
    progress_callback=None,
    manager: MCPRuntimeManager | None = None,
) -> dict[str, Any]:
    manager = manager or get_runtime_manager()
    prepared = await prepare_tool_call_tracking(
        session,
        installation,
        server,
        tool_name=tool_name,
        arguments=arguments,
        user_id=user_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        manager=manager,
    )

    try:
        result = await run_in_threadpool(
            execute_prepared_tool_call,
            prepared,
            tool_name=tool_name,
            arguments=arguments,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            request_meta=request_meta,
            progress_callback=progress_callback,
            manager=manager,
        )
    except Exception as exc:
        await finalize_prepared_tool_call(
            session,
            prepared,
            tool_name=tool_name,
            error=exc,
            reload=False,
        )
        raise

    await finalize_prepared_tool_call(
        session,
        prepared,
        tool_name=tool_name,
        result=result,
        reload=False,
    )
    return result


async def call_tool_with_isolated_tracking(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    cancel_event: Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    request_meta: dict[str, Any] | None = None,
    progress_callback=None,
    manager: MCPRuntimeManager | None = None,
    tracking_session_factory=AsyncSessionLocal,
) -> dict[str, Any]:
    manager = manager or get_runtime_manager()
    prepared = await prepare_tool_call_tracking(
        session,
        installation,
        server,
        tool_name=tool_name,
        arguments=arguments,
        user_id=user_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        manager=manager,
        defer_runtime_stops=True,
    )
    await session.commit()
    detach_prepared_tool_call(session, prepared)

    try:
        result = await run_in_threadpool(
            execute_prepared_tool_call,
            prepared,
            tool_name=tool_name,
            arguments=arguments,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            request_meta=request_meta,
            progress_callback=progress_callback,
            manager=manager,
        )
    except BaseException as exc:
        try:
            async with tracking_session_factory() as finalize_session:
                await finalize_prepared_tool_call(
                    finalize_session,
                    prepared,
                    tool_name=tool_name,
                    error=exc,
                )
                await finalize_session.commit()
        except Exception:
            logger.exception(
                "Unable to finalize failed MCP tool invocation %s.",
                prepared.invocation_id,
            )
        raise

    async with tracking_session_factory() as finalize_session:
        await finalize_prepared_tool_call(
            finalize_session,
            prepared,
            tool_name=tool_name,
            result=result,
        )
        await finalize_session.commit()
    return result


async def list_tools_with_tracking(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    manager: MCPRuntimeManager | None = None,
) -> list[dict[str, Any]]:
    manager = manager or get_runtime_manager()
    runtime_installation = await materialize_installation_secret_references(
        session,
        installation,
    )
    now = datetime.now(UTC)
    deferred_runtime_stops: list[MCPRuntimeSession] = []
    runtime_session = await ensure_runtime_session(
        session,
        runtime_installation,
        server,
        manager=manager,
        now=now,
        deferred_runtime_stops=deferred_runtime_stops,
    )
    runtime_session.status = "running"
    runtime_session.last_error = ""
    add_runtime_event(
        session,
        runtime_session,
        RUNTIME_EVENT_TOOL_CALL_STARTED,
        message="Tool discovery started.",
        metadata={"toolName": "tools/list"},
        now=now,
    )
    await session.flush()
    await session.commit()

    try:
        for deferred_runtime_session in deferred_runtime_stops:
            await run_in_threadpool(manager.stop_runtime, deferred_runtime_session)
        tools = await run_in_threadpool(
            manager.list_tools,
            runtime_installation,
            runtime_session=runtime_session,
        )
    except Exception as exc:
        failed_at = datetime.now(UTC)
        runtime_session.status = "idle"
        runtime_session.last_used_at = failed_at
        runtime_session.expires_at = runtime_expires_at(failed_at)
        runtime_session.failure_count += 1
        runtime_session.last_error = str(exc)
        add_runtime_event(
            session,
            runtime_session,
            RUNTIME_EVENT_TOOL_CALL_FAILED,
            message="Tool discovery failed.",
            metadata={
                "toolName": "tools/list",
                "errorType": exc.__class__.__name__,
            },
            now=failed_at,
        )
        await session.flush()
        raise

    finished_at = datetime.now(UTC)
    runtime_session.status = "idle"
    runtime_session.last_used_at = finished_at
    runtime_session.expires_at = runtime_expires_at(finished_at)
    runtime_session.last_error = ""
    add_runtime_event(
        session,
        runtime_session,
        RUNTIME_EVENT_TOOL_CALL_SUCCEEDED,
        message="Tool discovery succeeded.",
        metadata={
            "toolName": "tools/list",
            "toolCount": len(tools),
        },
        now=finished_at,
    )
    await session.flush()
    return tools


async def reap_expired_runtime_sessions(
    session: AsyncSession,
    *,
    manager: MCPRuntimeManager | None = None,
    limit: int = 100,
) -> MCPRuntimeReapResult:
    manager = manager or get_runtime_manager()
    now = datetime.now(UTC)
    expired_sessions = await repository.list_expired_runtime_sessions(
        session,
        now=now,
        limit=limit,
    )
    await session.commit()
    stopped_count = 0
    for runtime_session in expired_sessions:
        await run_in_threadpool(manager.stop_runtime, runtime_session)
        runtime_session.status = "stopped"
        runtime_session.stopped_at = now
        runtime_session.last_error = ""
        add_runtime_event(
            session,
            runtime_session,
            RUNTIME_EVENT_REAPER_STOPPED,
            message="Runtime session stopped by reaper.",
            metadata={"reason": "expired"},
            now=now,
        )
        await session.commit()
        stopped_count += 1
    return MCPRuntimeReapResult(stopped_count=stopped_count)


async def prune_runtime_events(
    session: AsyncSession,
    *,
    retention_days: int,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    return await repository.delete_runtime_events_before(
        session,
        cutoff=cutoff,
        limit=limit,
    )


async def recover_stale_tool_invocations(
    session: AsyncSession,
    *,
    stale_after_seconds: int,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    if stale_after_seconds < 1:
        return 0
    now = now or datetime.now(UTC)
    invocations = await repository.list_stale_running_tool_invocations(
        session,
        started_before=now - timedelta(seconds=stale_after_seconds),
        limit=limit,
    )
    for invocation in invocations:
        invocation.status = "failed"
        invocation.finished_at = now
        invocation.duration_ms = int((now - invocation.started_at).total_seconds() * 1000)
        invocation.output_size_bytes = 0
        invocation.is_error = True
        invocation.error = "Tool call did not finalize before the recovery deadline."
    await session.flush()
    return len(invocations)


async def prune_tool_invocations(
    session: AsyncSession,
    *,
    retention_days: int,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    return await repository.delete_tool_invocations_before(
        session,
        cutoff=cutoff,
        limit=limit,
    )


async def list_runtime_sessions(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
) -> MCPRuntimeSessionListResponse:
    sessions = await repository.list_runtime_sessions(
        session,
        workspace_id=workspace_id,
        status=status,
        limit=limit,
    )
    return MCPRuntimeSessionListResponse(
        sessions=[runtime_session_read(runtime_session) for runtime_session in sessions]
    )


async def get_runtime_summary(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    now: datetime | None = None,
) -> MCPRuntimeSummaryResponse:
    now = now or datetime.now(UTC)
    status_counts = await repository.count_runtime_sessions_by_status(
        session,
        workspace_id=workspace_id,
    )
    stale_active_sessions = await repository.count_stale_active_runtime_sessions(
        session,
        workspace_id=workspace_id,
        now=now,
    )
    tool_counts = await repository.count_tool_invocations(
        session,
        workspace_id=workspace_id,
    )
    recent_tool_counts = await repository.count_tool_invocations(
        session,
        workspace_id=workspace_id,
        started_since=now - RUNTIME_SUMMARY_RECENT_WINDOW,
    )
    recent_error_sessions = await repository.list_recent_error_runtime_sessions(
        session,
        workspace_id=workspace_id,
    )

    total_tool_calls, succeeded_tool_calls, failed_tool_calls, running_tool_calls = (
        summarize_tool_call_counts(tool_counts)
    )
    recent_total_tool_calls, _, recent_failed_tool_calls, _ = summarize_tool_call_counts(
        recent_tool_counts
    )
    recent_failure_rate = (
        recent_failed_tool_calls / recent_total_tool_calls
        if recent_total_tool_calls > 0
        else 0.0
    )

    server_errors: list[MCPRuntimeServerError] = []
    seen_servers: set[tuple[str, str]] = set()
    for runtime_session in recent_error_sessions:
        server_key = (runtime_session.server_name, runtime_session.server_version)
        if server_key in seen_servers:
            continue
        seen_servers.add(server_key)
        server_errors.append(runtime_server_error_read(runtime_session))

    return MCPRuntimeSummaryResponse(
        totalSessions=sum(status_counts.values()),
        activeSessions=sum(
            status_counts.get(runtime_status, 0)
            for runtime_status in repository.ACTIVE_RUNTIME_STATUSES
        ),
        idleSessions=status_counts.get("idle", 0),
        failedSessions=status_counts.get("failed", 0),
        stoppedSessions=status_counts.get("stopped", 0),
        expiredSessions=status_counts.get("expired", 0),
        staleActiveSessions=stale_active_sessions,
        sessionStatusCounts=status_counts,
        toolCalls=MCPRuntimeToolCallSummary(
            total=total_tool_calls,
            succeeded=succeeded_tool_calls,
            failed=failed_tool_calls,
            running=running_tool_calls,
            recentTotal=recent_total_tool_calls,
            recentFailed=recent_failed_tool_calls,
            recentFailureRate=round(recent_failure_rate, 4),
        ),
        recentServerErrors=server_errors,
    )


async def get_runtime_session(
    session: AsyncSession,
    runtime_session_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> MCPRuntimeSessionRead:
    runtime_session = await repository.get_runtime_session(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )
    if runtime_session is None:
        raise MCPRuntimeSessionNotFoundError("runtime session not found")
    return runtime_session_read(runtime_session)


async def get_runtime_session_health(
    session: AsyncSession,
    runtime_session_id: UUID,
    *,
    workspace_id: UUID | None = None,
    manager: MCPRuntimeManager | None = None,
) -> MCPRuntimeSessionHealthResponse:
    runtime_session = await repository.get_runtime_session(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )
    if runtime_session is None:
        raise MCPRuntimeSessionNotFoundError("runtime session not found")

    manager = manager or get_runtime_manager()
    await session.commit()
    health = await run_in_threadpool(manager.health_runtime, runtime_session)
    return MCPRuntimeSessionHealthResponse(
        runtimeSessionId=runtime_session.id,
        runtimeProvider=runtime_session.runtime_provider,
        runtimeKind=runtime_session.runtime_kind,
        status=health.status,
        healthy=health.healthy,
        ready=health.ready,
        message=health.message,
        details=health.details or {},
    )


async def stop_runtime_session(
    session: AsyncSession,
    runtime_session_id: UUID,
    *,
    workspace_id: UUID | None = None,
    manager: MCPRuntimeManager | None = None,
) -> MCPRuntimeSessionRead:
    manager = manager or get_runtime_manager()
    runtime_session = await repository.get_runtime_session(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )
    if runtime_session is None:
        raise MCPRuntimeSessionNotFoundError("runtime session not found")

    now = datetime.now(UTC)
    if runtime_session.status in repository.ACTIVE_RUNTIME_STATUSES:
        await session.commit()
        await run_in_threadpool(manager.stop_runtime, runtime_session)
        runtime_session.status = "stopped"
        runtime_session.stopped_at = now
        runtime_session.expires_at = now
        runtime_session.last_error = ""
        add_runtime_event(
            session,
            runtime_session,
            RUNTIME_EVENT_SESSION_STOPPED,
            message="Runtime session stopped.",
            metadata={"reason": "manual"},
            now=now,
        )
        await session.flush()
    return runtime_session_read(runtime_session)


async def list_runtime_events(
    session: AsyncSession,
    runtime_session_id: UUID,
    *,
    workspace_id: UUID | None = None,
    limit: int = 100,
) -> MCPRuntimeEventListResponse:
    runtime_session = await repository.get_runtime_session(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )
    if runtime_session is None:
        raise MCPRuntimeSessionNotFoundError("runtime session not found")
    events = await repository.list_runtime_events(session, runtime_session.id, limit=limit)
    return MCPRuntimeEventListResponse(
        events=[runtime_event_read(runtime_event) for runtime_event in events]
    )
