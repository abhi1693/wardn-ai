from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_runtime.models import (
    MCPRuntimeEvent,
    MCPRuntimeSession,
    MCPToolInvocation,
)

ACTIVE_RUNTIME_STATUSES = ("pending", "starting", "running", "idle")
TERMINAL_RUNTIME_STATUSES = ("stopped", "failed", "expired")


async def get_active_runtime_session(
    session: AsyncSession,
    installation_id: Any,
    *,
    now: datetime | None = None,
) -> MCPRuntimeSession | None:
    result = await session.execute(
        select(MCPRuntimeSession)
        .where(
            MCPRuntimeSession.installation_id == installation_id,
            MCPRuntimeSession.status.in_(ACTIVE_RUNTIME_STATUSES),
        )
        .order_by(MCPRuntimeSession.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_runtime_session(
    session: AsyncSession,
    runtime_session_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> MCPRuntimeSession | None:
    query = select(MCPRuntimeSession).where(MCPRuntimeSession.id == runtime_session_id)
    if workspace_id is not None:
        query = query.where(MCPRuntimeSession.workspace_id == workspace_id)
    result = await session.execute(
        query
    )
    return result.scalar_one_or_none()


async def list_runtime_sessions(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[MCPRuntimeSession]:
    query = select(MCPRuntimeSession)
    if workspace_id is not None:
        query = query.where(MCPRuntimeSession.workspace_id == workspace_id)
    if status:
        query = query.where(MCPRuntimeSession.status == status)
    result = await session.execute(
        query.order_by(MCPRuntimeSession.updated_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def list_active_runtime_sessions(
    session: AsyncSession,
    *,
    limit: int = 1000,
) -> list[MCPRuntimeSession]:
    result = await session.execute(
        select(MCPRuntimeSession)
        .where(MCPRuntimeSession.status.in_(ACTIVE_RUNTIME_STATUSES))
        .order_by(MCPRuntimeSession.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_runtime_sessions_by_status(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, int]:
    query = select(MCPRuntimeSession.status, func.count()).group_by(MCPRuntimeSession.status)
    if workspace_id is not None:
        query = query.where(MCPRuntimeSession.workspace_id == workspace_id)
    result = await session.execute(query)
    return {status: count for status, count in result.all()}


async def count_stale_active_runtime_sessions(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    query = select(func.count()).select_from(MCPRuntimeSession).where(
        MCPRuntimeSession.status.in_(ACTIVE_RUNTIME_STATUSES),
        MCPRuntimeSession.expires_at.is_not(None),
        MCPRuntimeSession.expires_at <= now,
    )
    if workspace_id is not None:
        query = query.where(MCPRuntimeSession.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.scalar_one()


async def count_tool_invocations(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    started_since: datetime | None = None,
) -> list[tuple[str, bool, int]]:
    query = select(
        MCPToolInvocation.status,
        MCPToolInvocation.is_error,
        func.count(),
    ).group_by(MCPToolInvocation.status, MCPToolInvocation.is_error)
    if workspace_id is not None:
        query = query.where(MCPToolInvocation.workspace_id == workspace_id)
    if started_since is not None:
        query = query.where(MCPToolInvocation.started_at >= started_since)
    result = await session.execute(query)
    return list(result.all())


async def list_recent_error_runtime_sessions(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    limit: int = 50,
) -> list[MCPRuntimeSession]:
    query = select(MCPRuntimeSession).where(MCPRuntimeSession.last_error != "")
    if workspace_id is not None:
        query = query.where(MCPRuntimeSession.workspace_id == workspace_id)
    result = await session.execute(
        query.order_by(MCPRuntimeSession.updated_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def create_runtime_session(
    *,
    installation_id: Any,
    workspace_id: Any | None = None,
    organization_id: Any | None = None,
    server_name: str,
    server_version: str,
    runtime_provider: str,
    runtime_kind: str,
    config_fingerprint: str,
    namespace: str,
    endpoint_url: str = "",
    pod_name: str = "",
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> MCPRuntimeSession:
    now = now or datetime.now(UTC)
    return MCPRuntimeSession(
        organization_id=organization_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name=server_name,
        server_version=server_version,
        runtime_provider=runtime_provider,
        runtime_kind=runtime_kind,
        config_fingerprint=config_fingerprint,
        status="running",
        pod_name=pod_name,
        namespace=namespace,
        endpoint_url=endpoint_url,
        started_at=now,
        ready_at=now,
        last_used_at=now,
        expires_at=expires_at,
        stopped_at=None,
        failure_count=0,
        last_error="",
    )


def create_tool_invocation(
    *,
    runtime_session: MCPRuntimeSession,
    installation_id: Any,
    server_name: str,
    server_version: str,
    tool_name: str,
    input_size_bytes: int,
    now: datetime | None = None,
) -> MCPToolInvocation:
    now = now or datetime.now(UTC)
    return MCPToolInvocation(
        organization_id=runtime_session.organization_id,
        workspace_id=runtime_session.workspace_id,
        runtime_session_id=runtime_session.id,
        installation_id=installation_id,
        server_name=server_name,
        server_version=server_version,
        tool_name=tool_name,
        status="running",
        started_at=now,
        finished_at=None,
        duration_ms=None,
        input_size_bytes=input_size_bytes,
        output_size_bytes=0,
        is_error=False,
        error="",
    )


def create_runtime_event(
    *,
    runtime_session_id: Any,
    event_type: str,
    message: str = "",
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> MCPRuntimeEvent:
    now = now or datetime.now(UTC)
    return MCPRuntimeEvent(
        runtime_session_id=runtime_session_id,
        event_type=event_type,
        message=message,
        event_metadata=metadata or {},
        created_at=now,
        updated_at=now,
    )


async def list_runtime_events(
    session: AsyncSession,
    runtime_session_id: UUID,
    *,
    limit: int = 100,
) -> list[MCPRuntimeEvent]:
    result = await session.execute(
        select(MCPRuntimeEvent)
        .where(MCPRuntimeEvent.runtime_session_id == runtime_session_id)
        .order_by(MCPRuntimeEvent.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_runtime_events_before(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> int:
    result = await session.execute(
        delete(MCPRuntimeEvent).where(MCPRuntimeEvent.created_at < cutoff)
    )
    return result.rowcount or 0


async def delete_tool_invocations_before(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> int:
    result = await session.execute(
        delete(MCPToolInvocation).where(MCPToolInvocation.started_at < cutoff)
    )
    return result.rowcount or 0


async def list_expired_runtime_sessions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[MCPRuntimeSession]:
    now = now or datetime.now(UTC)
    result = await session.execute(
        select(MCPRuntimeSession)
        .where(
            MCPRuntimeSession.status.in_(ACTIVE_RUNTIME_STATUSES),
            MCPRuntimeSession.expires_at.is_not(None),
            MCPRuntimeSession.expires_at <= now,
        )
        .order_by(MCPRuntimeSession.expires_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
