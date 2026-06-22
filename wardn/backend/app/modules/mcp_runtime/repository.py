from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_runtime.models import MCPRuntimeSession, MCPToolInvocation

ACTIVE_RUNTIME_STATUSES = ("pending", "starting", "running", "idle")


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


def create_runtime_session(
    *,
    installation_id: Any,
    workspace_id: Any | None = None,
    organization_id: Any | None = None,
    server_name: str,
    server_version: str,
    runtime_provider: str,
    runtime_kind: str,
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
