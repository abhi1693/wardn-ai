import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_runtime import repository
from app.modules.mcp_runtime.manager import (
    MCPRuntimeManager,
    get_runtime_manager,
    runtime_kind,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession


@dataclass(frozen=True)
class MCPRuntimeReapResult:
    stopped_count: int


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
    existing = await repository.get_active_runtime_session(
        session,
        installation.id,
        now=now,
    )
    expires_at = runtime_expires_at(now)
    if existing is not None:
        if existing.expires_at is not None and existing.expires_at <= now:
            existing.status = "stopped"
            existing.stopped_at = now
            await session.flush()
        else:
            existing.status = "running"
            existing.last_used_at = now
            existing.expires_at = expires_at
            existing.last_error = ""
            await session.flush()
            return existing

    runtime_session = repository.create_runtime_session(
        installation_id=installation.id,
        workspace_id=installation.workspace_id,
        server_name=server.name,
        server_version=server.version,
        runtime_provider=manager.provider_name(installation),
        runtime_kind=runtime_kind(installation),
        namespace=get_settings().mcp_runtime_namespace,
        now=now,
        expires_at=expires_at,
    )
    session.add(runtime_session)
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

    try:
        result = manager.call_tool(
            installation,
            tool_name=tool_name,
            arguments=arguments,
        )
    except Exception as exc:
        mark_invocation_failed(
            runtime_session,
            invocation,
            exc,
            now=datetime.now(UTC),
        )
        await session.flush()
        raise

    mark_invocation_success(
        runtime_session,
        invocation,
        result,
        now=datetime.now(UTC),
    )
    await session.flush()
    return result


async def reap_expired_runtime_sessions(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> MCPRuntimeReapResult:
    now = datetime.now(UTC)
    expired_sessions = await repository.list_expired_runtime_sessions(
        session,
        now=now,
        limit=limit,
    )
    for runtime_session in expired_sessions:
        runtime_session.status = "stopped"
        runtime_session.stopped_at = now
        runtime_session.last_error = ""
    await session.flush()
    return MCPRuntimeReapResult(stopped_count=len(expired_sessions))
