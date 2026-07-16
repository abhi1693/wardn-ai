from datetime import datetime
from uuid import UUID

from sqlalchemy import case, desc, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability.models import LLMModelPrice, LLMTrace, LLMUsageRecord
from app.modules.organizations.models import Workspace
from app.modules.users.models import User


async def list_mcp_tool_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int,
) -> list[tuple[MCPToolInvocation, User | None, Agent | None]]:
    result = await session.execute(
        select(MCPToolInvocation, User, Agent)
        .outerjoin(User, MCPToolInvocation.user_id == User.id)
        .outerjoin(Agent, MCPToolInvocation.agent_id == Agent.id)
        .where(
            MCPToolInvocation.workspace_id == workspace_id,
        )
        .order_by(desc(MCPToolInvocation.started_at), desc(MCPToolInvocation.created_at))
        .limit(limit)
    )
    return list(result.all())


async def list_llm_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int,
) -> list[tuple[LLMUsageRecord, User | None, Agent | None]]:
    result = await session.execute(
        select(LLMUsageRecord, User, Agent)
        .outerjoin(User, LLMUsageRecord.user_id == User.id)
        .outerjoin(Agent, LLMUsageRecord.agent_id == Agent.id)
        .where(
            LLMUsageRecord.organization_id == organization_id,
            LLMUsageRecord.workspace_id == workspace_id,
        )
        .order_by(desc(LLMUsageRecord.started_at), desc(LLMUsageRecord.created_at))
        .limit(limit)
    )
    return list(result.all())


def llm_usage_scope_filters(
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    started_at_from: datetime | None = None,
    started_at_to: datetime | None = None,
):
    filters = []
    if organization_id is not None:
        filters.append(LLMUsageRecord.organization_id == organization_id)
    if workspace_id is not None:
        filters.append(LLMUsageRecord.workspace_id == workspace_id)
    if user_id is not None:
        filters.append(LLMUsageRecord.user_id == user_id)
    if agent_run_id is not None:
        filters.append(LLMUsageRecord.agent_run_id == agent_run_id)
    if started_at_from is not None:
        filters.append(LLMUsageRecord.started_at >= started_at_from)
    if started_at_to is not None:
        filters.append(LLMUsageRecord.started_at < started_at_to)
    return filters


def mcp_tool_scope_filters(
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    started_at_from: datetime | None = None,
    started_at_to: datetime | None = None,
):
    filters = []
    if organization_id is not None:
        filters.append(MCPToolInvocation.organization_id == organization_id)
    if workspace_id is not None:
        filters.append(MCPToolInvocation.workspace_id == workspace_id)
    if user_id is not None:
        filters.append(MCPToolInvocation.user_id == user_id)
    if agent_run_id is not None:
        filters.append(MCPToolInvocation.agent_run_id == agent_run_id)
    if started_at_from is not None:
        filters.append(MCPToolInvocation.started_at >= started_at_from)
    if started_at_to is not None:
        filters.append(MCPToolInvocation.started_at < started_at_to)
    return filters


def llm_usage_aggregate_columns():
    return (
        func.count(LLMUsageRecord.id).label("requests"),
        func.coalesce(
            func.sum(case((LLMUsageRecord.status == "succeeded", 1), else_=0)),
            0,
        ).label("succeeded"),
        func.coalesce(
            func.sum(case((LLMUsageRecord.status == "failed", 1), else_=0)),
            0,
        ).label("failed"),
        func.coalesce(
            func.sum(case((LLMUsageRecord.status == "running", 1), else_=0)),
            0,
        ).label("running"),
        func.coalesce(func.sum(LLMUsageRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(LLMUsageRecord.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(LLMUsageRecord.cost_usd), 0).label("cost_usd"),
    )


async def llm_usage_totals(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
):
    result = await session.execute(
        select(*llm_usage_aggregate_columns()).where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_run_id=agent_run_id,
            )
        )
    )
    return result.one()


async def mcp_tool_call_count(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
) -> int:
    result = await session.execute(
        select(func.count(MCPToolInvocation.id)).where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_run_id=agent_run_id,
            )
        )
    )
    return int(result.scalar_one() or 0)


async def llm_usage_summary_rows(
    session: AsyncSession,
    *,
    started_at_from: datetime,
    started_at_to: datetime,
    breakdown_limit: int,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    usage_day = func.date(func.timezone("UTC", LLMUsageRecord.started_at))
    grouped = (
        select(
            LLMUsageRecord.user_id,
            LLMUsageRecord.workspace_id,
            LLMUsageRecord.agent_id,
            LLMUsageRecord.provider,
            LLMUsageRecord.model,
            usage_day.label("usage_day"),
            func.grouping(LLMUsageRecord.user_id).label("group_user"),
            func.grouping(LLMUsageRecord.workspace_id).label("group_workspace"),
            func.grouping(LLMUsageRecord.agent_id).label("group_agent"),
            func.grouping(LLMUsageRecord.provider).label("group_model"),
            func.grouping(usage_day).label("group_day"),
            *llm_usage_aggregate_columns(),
        )
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(
            func.grouping_sets(
                tuple_(),
                tuple_(LLMUsageRecord.user_id),
                tuple_(LLMUsageRecord.workspace_id),
                tuple_(LLMUsageRecord.agent_id),
                tuple_(LLMUsageRecord.provider, LLMUsageRecord.model),
                tuple_(usage_day),
            )
        )
        .cte("llm_usage_grouped")
    )
    group_key = case(
        (grouped.c.group_user == 0, literal("user")),
        (grouped.c.group_workspace == 0, literal("workspace")),
        (grouped.c.group_agent == 0, literal("agent")),
        (grouped.c.group_model == 0, literal("model")),
        (grouped.c.group_day == 0, literal("day")),
        else_=literal("total"),
    ).label("group_key")
    ranked = select(
        grouped,
        group_key,
        func.row_number()
        .over(
            partition_by=group_key,
            order_by=(grouped.c.cost_usd.desc(), grouped.c.requests.desc()),
        )
        .label("group_rank"),
    ).cte("llm_usage_ranked")
    result = await session.execute(
        select(
            ranked,
            User.first_name,
            User.last_name,
            User.email,
            Workspace.name.label("workspace_name"),
            Agent.name.label("agent_name"),
        )
        .outerjoin(User, ranked.c.user_id == User.id)
        .outerjoin(Workspace, ranked.c.workspace_id == Workspace.id)
        .outerjoin(Agent, ranked.c.agent_id == Agent.id)
        .where(
            or_(
                ranked.c.group_key.in_(("total", "day")),
                ranked.c.group_rank <= max(1, breakdown_limit),
            )
        )
        .order_by(ranked.c.group_key, ranked.c.group_rank)
    )
    return list(result.mappings().all())


async def mcp_tool_usage_summary_rows(
    session: AsyncSession,
    *,
    started_at_from: datetime,
    started_at_to: datetime,
    breakdown_limit: int,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    usage_day = func.date(func.timezone("UTC", MCPToolInvocation.started_at))
    grouped = (
        select(
            MCPToolInvocation.user_id,
            MCPToolInvocation.workspace_id,
            MCPToolInvocation.agent_id,
            usage_day.label("usage_day"),
            func.grouping(MCPToolInvocation.user_id).label("group_user"),
            func.grouping(MCPToolInvocation.workspace_id).label("group_workspace"),
            func.grouping(MCPToolInvocation.agent_id).label("group_agent"),
            func.grouping(usage_day).label("group_day"),
            func.count(MCPToolInvocation.id).label("tool_calls"),
        )
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                started_at_from=started_at_from,
                started_at_to=started_at_to,
            )
        )
        .group_by(
            func.grouping_sets(
                tuple_(),
                tuple_(MCPToolInvocation.user_id),
                tuple_(MCPToolInvocation.workspace_id),
                tuple_(MCPToolInvocation.agent_id),
                tuple_(usage_day),
            )
        )
        .cte("mcp_tool_usage_grouped")
    )
    group_key = case(
        (grouped.c.group_user == 0, literal("user")),
        (grouped.c.group_workspace == 0, literal("workspace")),
        (grouped.c.group_agent == 0, literal("agent")),
        (grouped.c.group_day == 0, literal("day")),
        else_=literal("total"),
    ).label("group_key")
    ranked = select(
        grouped,
        group_key,
        func.row_number()
        .over(
            partition_by=group_key,
            order_by=grouped.c.tool_calls.desc(),
        )
        .label("group_rank"),
    ).cte("mcp_tool_usage_ranked")
    result = await session.execute(
        select(
            ranked,
            User.first_name,
            User.last_name,
            User.email,
            Workspace.name.label("workspace_name"),
            Agent.name.label("agent_name"),
        )
        .outerjoin(User, ranked.c.user_id == User.id)
        .outerjoin(Workspace, ranked.c.workspace_id == Workspace.id)
        .outerjoin(Agent, ranked.c.agent_id == Agent.id)
        .where(
            or_(
                ranked.c.group_key.in_(("total", "day")),
                ranked.c.group_rank <= max(1, breakdown_limit),
            )
        )
        .order_by(ranked.c.group_key, ranked.c.group_rank)
    )
    return list(result.mappings().all())


async def list_llm_usage_records_for_agent_run(
    session: AsyncSession,
    *,
    agent_run_id: UUID,
) -> list[LLMUsageRecord]:
    result = await session.execute(
        select(LLMUsageRecord)
        .where(LLMUsageRecord.agent_run_id == agent_run_id)
        .order_by(LLMUsageRecord.started_at, LLMUsageRecord.created_at)
    )
    return list(result.scalars().all())


async def list_model_prices(session: AsyncSession) -> list[LLMModelPrice]:
    result = await session.execute(
        select(LLMModelPrice).order_by(LLMModelPrice.provider, LLMModelPrice.model)
    )
    return list(result.scalars().all())


async def get_model_price_by_id(
    session: AsyncSession,
    *,
    price_id: UUID,
) -> LLMModelPrice | None:
    result = await session.execute(
        select(LLMModelPrice).where(LLMModelPrice.id == price_id)
    )
    return result.scalar_one_or_none()


async def get_model_price(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
) -> LLMModelPrice | None:
    result = await session.execute(
        select(LLMModelPrice).where(
            LLMModelPrice.provider == provider,
            LLMModelPrice.model == model,
        )
    )
    return result.scalar_one_or_none()


async def save_model_price(
    session: AsyncSession,
    *,
    model_price: LLMModelPrice,
) -> LLMModelPrice:
    session.add(model_price)
    await session.flush()
    return model_price


async def delete_model_price(
    session: AsyncSession,
    *,
    model_price: LLMModelPrice,
) -> None:
    await session.delete(model_price)


async def create_llm_usage_record(
    session: AsyncSession,
    *,
    usage_record: LLMUsageRecord,
    trace: LLMTrace,
) -> LLMUsageRecord:
    session.add(trace)
    session.add(usage_record)
    await session.flush()
    return usage_record
