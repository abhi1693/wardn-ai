import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_runtime import repository
from app.modules.mcp_runtime.manager import (
    MCPRuntimeManager,
    get_runtime_manager,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
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
RUNTIME_EVENT_SHUTDOWN_STOP_FAILED = "runtime_shutdown_stop_failed"
RUNTIME_SUMMARY_RECENT_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class MCPRuntimeReapResult:
    stopped_count: int
    deleted_event_count: int = 0
    deleted_invocation_count: int = 0


@dataclass(frozen=True)
class MCPRuntimeWarmupResult:
    warmed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True)
class MCPRuntimeShutdownResult:
    stopped_count: int = 0
    failed_count: int = 0


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


def payload_size_bytes(payload: Any) -> int:
    try:
        return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except TypeError:
        return 0


def runtime_expires_at(now: datetime | None = None) -> datetime:
    settings = get_settings()
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=settings.mcp_runtime_idle_timeout_seconds)


async def ensure_runtime_session(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    manager: MCPRuntimeManager,
    now: datetime | None = None,
) -> MCPRuntimeSession:
    now = now or datetime.now(UTC)
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
            manager.stop_runtime(existing)
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
    session.add(runtime_session)
    await session.flush()
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
    now = now or datetime.now(UTC)
    server = MCPServerVersion(
        name=installation.server_name,
        version=installation.installed_version,
    )
    runtime_session = await ensure_runtime_session(
        session,
        installation,
        server,
        manager=manager,
        now=now,
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

    try:
        health = await run_in_threadpool(
            manager.ensure_runtime,
            installation,
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
    error: Exception,
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


async def call_tool_with_tracking(
    session: AsyncSession,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    manager: MCPRuntimeManager | None = None,
) -> dict[str, Any]:
    manager = manager or get_runtime_manager()
    now = datetime.now(UTC)
    runtime_session = await ensure_runtime_session(
        session,
        installation,
        server,
        manager=manager,
        now=now,
    )
    invocation = repository.create_tool_invocation(
        runtime_session=runtime_session,
        installation_id=installation.id,
        server_name=server.name,
        server_version=server.version,
        tool_name=tool_name,
        input_size_bytes=payload_size_bytes(arguments),
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

    try:
        result = await run_in_threadpool(
            manager.call_tool,
            installation,
            tool_name=tool_name,
            arguments=arguments,
            runtime_session=runtime_session,
        )
    except Exception as exc:
        mark_invocation_failed(
            runtime_session,
            invocation,
            exc,
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
                "errorType": exc.__class__.__name__,
            },
        )
        await session.flush()
        raise

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
    await session.flush()
    return result


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
    for runtime_session in expired_sessions:
        manager.stop_runtime(runtime_session)
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
    await session.flush()
    return MCPRuntimeReapResult(stopped_count=len(expired_sessions))


async def shutdown_active_runtime_sessions(
    session: AsyncSession,
    *,
    manager: MCPRuntimeManager | None = None,
    limit: int = 1000,
) -> MCPRuntimeShutdownResult:
    manager = manager or get_runtime_manager()
    stopped_count = 0
    failed_count = 0
    batch_limit = max(1, limit)

    while True:
        runtime_sessions = await repository.list_active_runtime_sessions(
            session,
            limit=batch_limit,
        )
        if not runtime_sessions:
            break

        now = datetime.now(UTC)
        for runtime_session in runtime_sessions:
            try:
                await run_in_threadpool(
                    manager.stop_runtime,
                    runtime_session,
                    delete_resources=True,
                )
            except Exception as exc:
                failed_count += 1
                runtime_session.status = "failed"
                runtime_session.expires_at = now
                runtime_session.failure_count += 1
                runtime_session.last_error = str(exc)
                add_runtime_event(
                    session,
                    runtime_session,
                    RUNTIME_EVENT_SHUTDOWN_STOP_FAILED,
                    message="Runtime session shutdown teardown failed.",
                    metadata={
                        "reason": "server_shutdown",
                        "errorType": exc.__class__.__name__,
                    },
                    now=now,
                )
                continue

            stopped_count += 1
            runtime_session.status = "stopped"
            runtime_session.stopped_at = now
            runtime_session.expires_at = now
            runtime_session.last_error = ""
            add_runtime_event(
                session,
                runtime_session,
                RUNTIME_EVENT_SESSION_STOPPED,
                message="Runtime session stopped during server shutdown.",
                metadata={"reason": "server_shutdown"},
                now=now,
            )

        await session.flush()
        if len(runtime_sessions) < batch_limit:
            break

    return MCPRuntimeShutdownResult(
        stopped_count=stopped_count,
        failed_count=failed_count,
    )


async def prune_runtime_events(
    session: AsyncSession,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    return await repository.delete_runtime_events_before(session, cutoff=cutoff)


async def prune_tool_invocations(
    session: AsyncSession,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    if retention_days < 1:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    return await repository.delete_tool_invocations_before(session, cutoff=cutoff)


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
        raise LookupError("runtime session not found")
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
        raise LookupError("runtime session not found")

    manager = manager or get_runtime_manager()
    health = manager.health_runtime(runtime_session)
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
        raise LookupError("runtime session not found")

    now = datetime.now(UTC)
    if runtime_session.status in repository.ACTIVE_RUNTIME_STATUSES:
        manager.stop_runtime(runtime_session)
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
        raise LookupError("runtime session not found")
    events = await repository.list_runtime_events(session, runtime_session.id, limit=limit)
    return MCPRuntimeEventListResponse(
        events=[runtime_event_read(runtime_event) for runtime_event in events]
    )
