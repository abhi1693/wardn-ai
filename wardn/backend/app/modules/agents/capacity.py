import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import AsyncSessionLocal
from app.modules.agents import repository
from app.modules.agents.exceptions import AgentCapacityUnavailableError
from app.modules.agents.models import AgentRun
from app.modules.limits import service as limits_service
from app.modules.limits.exceptions import LimitExceededError

GLOBAL_AGENT_RUN_CAPACITY_SCOPE_ID = uuid.UUID(int=0)


async def reserve_agent_run(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    triggered_by_id: uuid.UUID | None,
    previous_agent_run_id: uuid.UUID | None,
    trigger_type: str,
    settings: Settings | None = None,
    scheduled_run_id: uuid.UUID | None = None,
) -> AgentRun:
    settings = settings or get_settings()
    deadline = (
        asyncio.get_running_loop().time()
        + settings.hosted_cloud_agent_run_queue_wait_seconds
    )
    organization_full = False

    while True:
        async with AsyncSessionLocal() as session:
            await limits_service.lock_quota_capacity(
                session,
                [
                    limits_service.quota_scope(
                        limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION,
                        GLOBAL_AGENT_RUN_CAPACITY_SCOPE_ID,
                    ),
                    limits_service.quota_scope(
                        limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION,
                        organization_id,
                    ),
                ],
            )
            active_since = datetime.now(UTC) - timedelta(
                seconds=settings.hosted_cloud_agent_run_stale_seconds
            )
            organization_count = await repository.count_running_agent_runs(
                session,
                organization_id=organization_id,
                active_since=active_since,
            )
            global_count = await repository.count_running_agent_runs(
                session,
                active_since=active_since,
            )
            try:
                await limits_service.require_limit_available(
                    session,
                    limit_key=limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION,
                    scope_chain=[("organization", organization_id)],
                    current_count=organization_count,
                )
                organization_full = False
            except LimitExceededError:
                organization_full = True

            if (
                not organization_full
                and global_count < settings.hosted_cloud_global_concurrent_agent_runs
            ):
                agent_run = await repository.create_agent_run(
                    session,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    previous_agent_run_id=previous_agent_run_id,
                    triggered_by_id=triggered_by_id,
                    trigger_type=trigger_type,
                    scheduled_run_id=scheduled_run_id,
                )
                await session.commit()
                return agent_run
            await session.rollback()

        if asyncio.get_running_loop().time() >= deadline:
            if organization_full:
                raise LimitExceededError(
                    "agent_runs.concurrent.per_organization limit exceeded"
                )
            raise AgentCapacityUnavailableError(
                "hosted agent capacity is busy; retry shortly"
            )
        await asyncio.sleep(settings.hosted_cloud_agent_run_queue_poll_seconds)


async def require_resume_capacity(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    if not settings.hosted_cloud_mode:
        return
    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION,
                GLOBAL_AGENT_RUN_CAPACITY_SCOPE_ID,
            ),
            limits_service.quota_scope(
                limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION,
                organization_id,
            ),
        ],
    )
    active_since = datetime.now(UTC) - timedelta(
        seconds=settings.hosted_cloud_agent_run_stale_seconds
    )
    organization_count = await repository.count_running_agent_runs(
        session,
        organization_id=organization_id,
        active_since=active_since,
    )
    global_count = await repository.count_running_agent_runs(
        session,
        active_since=active_since,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.CONCURRENT_AGENT_RUNS_PER_ORGANIZATION,
        scope_chain=[("organization", organization_id)],
        current_count=organization_count,
    )
    if global_count >= settings.hosted_cloud_global_concurrent_agent_runs:
        raise AgentCapacityUnavailableError("hosted agent capacity is busy; retry shortly")
