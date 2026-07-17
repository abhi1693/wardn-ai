from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry.models import MCPRepositoryMetadataRateLimit


@dataclass(frozen=True)
class RepositoryMetadataRateLimitResult:
    allowed: bool
    retry_after_seconds: int


async def consume_repository_metadata_rate_limit(
    session: AsyncSession,
    organization_id: UUID,
    *,
    limit: int,
    window_seconds: int,
    now: datetime | None = None,
) -> RepositoryMetadataRateLimitResult:
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(seconds=window_seconds)
    window_expired = MCPRepositoryMetadataRateLimit.window_started_at <= cutoff
    statement = (
        insert(MCPRepositoryMetadataRateLimit)
        .values(
            organization_id=organization_id,
            window_started_at=current_time,
            request_count=1,
        )
        .on_conflict_do_update(
            index_elements=[MCPRepositoryMetadataRateLimit.organization_id],
            set_={
                "window_started_at": case(
                    (window_expired, current_time),
                    else_=MCPRepositoryMetadataRateLimit.window_started_at,
                ),
                "request_count": case(
                    (window_expired, 1),
                    else_=MCPRepositoryMetadataRateLimit.request_count + 1,
                ),
            },
        )
        .returning(
            MCPRepositoryMetadataRateLimit.window_started_at,
            MCPRepositoryMetadataRateLimit.request_count,
        )
    )
    window_started_at, request_count = (await session.execute(statement)).one()
    retry_after = max(
        1,
        int(
            (
                window_started_at
                + timedelta(seconds=window_seconds)
                - current_time
            ).total_seconds()
        )
        + 1,
    )
    return RepositoryMetadataRateLimitResult(
        allowed=request_count <= limit,
        retry_after_seconds=retry_after,
    )
