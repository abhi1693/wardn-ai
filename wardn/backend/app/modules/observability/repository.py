from uuid import UUID

from sqlalchemy import case, desc, func, select
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
    return filters


def mcp_tool_scope_filters(
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_run_id: UUID | None = None,
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


def llm_usage_order_columns():
    return (
        desc(func.coalesce(func.sum(LLMUsageRecord.cost_usd), 0)),
        desc(func.count(LLMUsageRecord.id)),
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


async def llm_usage_by_user(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            LLMUsageRecord.user_id,
            User.first_name,
            User.last_name,
            User.email,
            *llm_usage_aggregate_columns(),
        )
        .outerjoin(User, LLMUsageRecord.user_id == User.id)
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(LLMUsageRecord.user_id, User.first_name, User.last_name, User.email)
        .order_by(*llm_usage_order_columns())
    )
    return list(result.all())


async def llm_usage_by_workspace(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            LLMUsageRecord.workspace_id,
            Workspace.name,
            *llm_usage_aggregate_columns(),
        )
        .outerjoin(Workspace, LLMUsageRecord.workspace_id == Workspace.id)
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(LLMUsageRecord.workspace_id, Workspace.name)
        .order_by(*llm_usage_order_columns())
    )
    return list(result.all())


async def llm_usage_by_agent(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            LLMUsageRecord.agent_id,
            Agent.name,
            *llm_usage_aggregate_columns(),
        )
        .outerjoin(Agent, LLMUsageRecord.agent_id == Agent.id)
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(LLMUsageRecord.agent_id, Agent.name)
        .order_by(*llm_usage_order_columns())
    )
    return list(result.all())


async def llm_usage_by_model(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            LLMUsageRecord.provider,
            LLMUsageRecord.model,
            *llm_usage_aggregate_columns(),
        )
        .where(
            *llm_usage_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(LLMUsageRecord.provider, LLMUsageRecord.model)
        .order_by(*llm_usage_order_columns())
    )
    return list(result.all())


async def mcp_tool_calls_by_user(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            MCPToolInvocation.user_id,
            User.first_name,
            User.last_name,
            User.email,
            func.count(MCPToolInvocation.id),
        )
        .outerjoin(User, MCPToolInvocation.user_id == User.id)
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(MCPToolInvocation.user_id, User.first_name, User.last_name, User.email)
    )
    return list(result.all())


async def mcp_tool_calls_by_workspace(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            MCPToolInvocation.workspace_id,
            Workspace.name,
            func.count(MCPToolInvocation.id),
        )
        .outerjoin(Workspace, MCPToolInvocation.workspace_id == Workspace.id)
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(MCPToolInvocation.workspace_id, Workspace.name)
    )
    return list(result.all())


async def mcp_tool_calls_by_agent(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
):
    result = await session.execute(
        select(
            MCPToolInvocation.agent_id,
            Agent.name,
            func.count(MCPToolInvocation.id),
        )
        .outerjoin(Agent, MCPToolInvocation.agent_id == Agent.id)
        .where(
            *mcp_tool_scope_filters(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        .group_by(MCPToolInvocation.agent_id, Agent.name)
    )
    return list(result.all())


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
    if not hasattr(session, "execute"):
        return None
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
