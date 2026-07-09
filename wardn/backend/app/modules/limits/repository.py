import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.models import ResourceLimit, UsageBudget
from app.modules.observability.models import LLMUsageRecord


async def list_limits(
    session: AsyncSession,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    limit_key: str | None = None,
) -> list[ResourceLimit]:
    statement = select(ResourceLimit).order_by(
        ResourceLimit.scope_type.asc(),
        ResourceLimit.limit_key.asc(),
        ResourceLimit.created_at.asc(),
    )
    if scope_type is not None:
        statement = statement.where(ResourceLimit.scope_type == scope_type)
    if scope_id is not None:
        statement = statement.where(ResourceLimit.scope_id == scope_id)
    if limit_key is not None:
        statement = statement.where(ResourceLimit.limit_key == limit_key)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_limit_by_id(
    session: AsyncSession,
    limit_id: uuid.UUID,
) -> ResourceLimit | None:
    return await session.get(ResourceLimit, limit_id)


async def get_limit(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: uuid.UUID,
    limit_key: str,
) -> ResourceLimit | None:
    result = await session.execute(
        select(ResourceLimit).where(
            ResourceLimit.scope_type == scope_type,
            ResourceLimit.scope_id == scope_id,
            ResourceLimit.limit_key == limit_key,
        )
    )
    return result.scalar_one_or_none()


async def list_usage_budgets(
    session: AsyncSession,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    budget_key: str | None = None,
) -> list[UsageBudget]:
    statement = select(UsageBudget).order_by(
        UsageBudget.scope_type.asc(),
        UsageBudget.budget_key.asc(),
        UsageBudget.created_at.asc(),
    )
    if scope_type is not None:
        statement = statement.where(UsageBudget.scope_type == scope_type)
    if scope_id is not None:
        statement = statement.where(UsageBudget.scope_id == scope_id)
    if budget_key is not None:
        statement = statement.where(UsageBudget.budget_key == budget_key)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_usage_budgets_for_scopes(
    session: AsyncSession,
    *,
    scope_chain: list[tuple[str, uuid.UUID]],
    model: str,
) -> list[UsageBudget]:
    if not scope_chain:
        return []
    scope_filters = [
        and_(UsageBudget.scope_type == scope_type, UsageBudget.scope_id == scope_id)
        for scope_type, scope_id in scope_chain
    ]
    result = await session.execute(
        select(UsageBudget)
        .where(
            or_(*scope_filters),
            UsageBudget.model_filter.in_(["", model]),
        )
        .order_by(UsageBudget.scope_type.asc(), UsageBudget.budget_key.asc())
    )
    return list(result.scalars().all())


async def get_usage_budget_by_id(
    session: AsyncSession,
    budget_id: uuid.UUID,
) -> UsageBudget | None:
    return await session.get(UsageBudget, budget_id)


async def get_usage_budget(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: uuid.UUID,
    budget_key: str,
    model_filter: str,
) -> UsageBudget | None:
    result = await session.execute(
        select(UsageBudget).where(
            UsageBudget.scope_type == scope_type,
            UsageBudget.scope_id == scope_id,
            UsageBudget.budget_key == budget_key,
            UsageBudget.model_filter == model_filter,
        )
    )
    return result.scalar_one_or_none()


async def llm_usage_budget_spend(
    session: AsyncSession,
    *,
    budget: UsageBudget,
    window_start: datetime,
    window_end: datetime,
) -> Decimal:
    filters = [
        LLMUsageRecord.started_at >= window_start,
        LLMUsageRecord.started_at < window_end,
    ]
    if budget.scope_type == "organization":
        filters.append(LLMUsageRecord.organization_id == budget.scope_id)
    elif budget.scope_type == "workspace":
        filters.append(LLMUsageRecord.workspace_id == budget.scope_id)
    elif budget.scope_type == "user":
        filters.append(LLMUsageRecord.user_id == budget.scope_id)
    elif budget.scope_type == "agent":
        filters.append(LLMUsageRecord.agent_id == budget.scope_id)
    if budget.model_filter:
        filters.append(LLMUsageRecord.model == budget.model_filter)

    if budget.unit == "cost_usd":
        expression = func.coalesce(func.sum(LLMUsageRecord.cost_usd), 0)
    elif budget.unit == "tokens":
        expression = func.coalesce(
            func.sum(LLMUsageRecord.input_tokens + LLMUsageRecord.output_tokens),
            0,
        )
    else:
        expression = func.count(LLMUsageRecord.id)

    result = await session.execute(select(expression).where(*filters))
    value = result.scalar_one()
    return value if isinstance(value, Decimal) else Decimal(str(value))
