import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits import repository
from app.modules.limits.exceptions import (
    InvalidLimitKeyError,
    InvalidLimitScopeError,
    LimitAccessDeniedError,
    LimitExceededError,
    LimitNotFoundError,
)
from app.modules.limits.models import ResourceLimit
from app.modules.limits.schemas import (
    ResourceLimitListResponse,
    ResourceLimitRead,
    ResourceLimitUpsert,
    UsageBudgetListResponse,
    UsageBudgetRead,
    UsageBudgetUpsert,
)
from app.modules.users.models import User

SCOPE_TYPES = {"organization", "workspace"}
USAGE_BUDGET_SCOPE_TYPES = {"organization", "workspace", "user", "agent"}
USAGE_BUDGET_UNITS = {"cost_usd", "tokens", "requests"}
USAGE_BUDGET_PERIODS = {"hour", "day", "month"}

WORKSPACES_PER_ORGANIZATION = "workspaces.per_organization"
WORKSPACES_CREATED_PER_USER = "workspaces.created_per_user"
AGENTS_PER_ORGANIZATION = "agents.per_organization"
AGENTS_PER_WORKSPACE = "agents.per_workspace"
AGENTS_PER_WORKSPACE_PER_USER = "agents.per_workspace_per_user"
WORKSPACE_CONVERSATIONS_PER_WORKSPACE = "workspace_conversations.per_workspace"
WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER = (
    "workspace_conversations.per_workspace_per_user"
)
GUARDRAIL_POLICIES_PER_WORKSPACE = "guardrail_policies.per_workspace"
GUARDRAIL_POLICIES_PER_WORKSPACE_PER_USER = "guardrail_policies.per_workspace_per_user"
MCP_CATALOG_SOURCES_PER_ORGANIZATION = "mcp_catalog_sources.per_organization"
MCP_SERVER_VERSIONS_PER_ORGANIZATION = "mcp_server_versions.per_organization"
MCP_SERVER_INSTALLATIONS_PER_WORKSPACE = "mcp_server_installations.per_workspace"
SECRET_STORES_PER_ORGANIZATION = "secret_stores.per_organization"
SECRET_STORES_PER_WORKSPACE = "secret_stores.per_workspace"
SECRET_HANDLES_PER_ORGANIZATION = "secret_handles.per_organization"
SECRET_HANDLES_PER_WORKSPACE = "secret_handles.per_workspace"
LLM_PROVIDER_CREDENTIALS_PER_ORGANIZATION = "llm_provider_credentials.per_organization"
LLM_PROVIDER_CREDENTIALS_PER_WORKSPACE = "llm_provider_credentials.per_workspace"
LLM_PROVIDER_CREDENTIALS_PER_USER = "llm_provider_credentials.per_user"

LLM_BUDGET_KEYS = {
    f"llm.{unit}.per_{period}": (unit, period)
    for unit in ("cost_usd", "tokens", "requests")
    for period in ("hour", "day", "month")
}

SUPPORTED_LIMIT_KEYS = {
    WORKSPACES_PER_ORGANIZATION,
    WORKSPACES_CREATED_PER_USER,
    AGENTS_PER_ORGANIZATION,
    AGENTS_PER_WORKSPACE,
    AGENTS_PER_WORKSPACE_PER_USER,
    WORKSPACE_CONVERSATIONS_PER_WORKSPACE,
    WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER,
    GUARDRAIL_POLICIES_PER_WORKSPACE,
    GUARDRAIL_POLICIES_PER_WORKSPACE_PER_USER,
    MCP_CATALOG_SOURCES_PER_ORGANIZATION,
    MCP_SERVER_VERSIONS_PER_ORGANIZATION,
    MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
    SECRET_STORES_PER_ORGANIZATION,
    SECRET_STORES_PER_WORKSPACE,
    SECRET_HANDLES_PER_ORGANIZATION,
    SECRET_HANDLES_PER_WORKSPACE,
    LLM_PROVIDER_CREDENTIALS_PER_ORGANIZATION,
    LLM_PROVIDER_CREDENTIALS_PER_WORKSPACE,
    LLM_PROVIDER_CREDENTIALS_PER_USER,
}


@dataclass(frozen=True)
class LLMBudgetContext:
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    model: str
    now: datetime | None = None


@dataclass(frozen=True)
class QuotaScope:
    """A count domain that must be serialized while capacity is checked and consumed."""

    limit_key: str
    subject_ids: tuple[uuid.UUID, ...]


def quota_scope(limit_key: str, *subject_ids: uuid.UUID) -> QuotaScope:
    if not subject_ids:
        raise ValueError("quota scope requires at least one subject")
    return QuotaScope(normalize_limit_key(limit_key), subject_ids)


def quota_lock_id(scope: QuotaScope) -> int:
    canonical = ":".join((scope.limit_key, *(str(value) for value in scope.subject_ids)))
    digest = hashlib.blake2b(
        canonical.encode(),
        digest_size=8,
        person=b"wardnquota",
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def lock_quota_capacity(
    session: AsyncSession,
    scopes: Iterable[QuotaScope],
) -> None:
    """Acquire deadlock-safe PostgreSQL transaction locks for quota count domains."""
    lock_ids = sorted({quota_lock_id(scope) for scope in scopes})
    for lock_id in lock_ids:
        await session.execute(select(func.pg_advisory_xact_lock(lock_id)))


def require_limits_admin(user: User) -> None:
    if not user.is_superuser:
        raise LimitAccessDeniedError("only superusers can manage limits")


def normalize_limit_key(value: str) -> str:
    normalized_key = value.strip().casefold()
    if normalized_key not in SUPPORTED_LIMIT_KEYS:
        raise InvalidLimitKeyError("unsupported limit key")
    return normalized_key


def normalize_scope_type(value: str) -> str:
    normalized_type = value.strip().casefold()
    if normalized_type not in SCOPE_TYPES:
        raise InvalidLimitScopeError("invalid limit scope type")
    return normalized_type


def normalize_usage_budget_scope_type(value: str) -> str:
    normalized_type = value.strip().casefold()
    if normalized_type not in USAGE_BUDGET_SCOPE_TYPES:
        raise InvalidLimitScopeError("invalid usage budget scope type")
    return normalized_type


def normalize_usage_budget_key(value: str) -> str:
    normalized_key = value.strip().casefold()
    if normalized_key not in LLM_BUDGET_KEYS:
        raise InvalidLimitKeyError("unsupported usage budget key")
    return normalized_key


def usage_budget_unit_period(
    budget_key: str,
    unit: str | None,
    period: str | None,
) -> tuple[str, str]:
    normalized_key = normalize_usage_budget_key(budget_key)
    key_unit, key_period = LLM_BUDGET_KEYS[normalized_key]
    normalized_unit = unit.strip().casefold() if unit else key_unit
    normalized_period = period.strip().casefold() if period else key_period
    if normalized_unit not in USAGE_BUDGET_UNITS:
        raise InvalidLimitKeyError("invalid usage budget unit")
    if normalized_period not in USAGE_BUDGET_PERIODS:
        raise InvalidLimitKeyError("invalid usage budget period")
    if (normalized_unit, normalized_period) != (key_unit, key_period):
        raise InvalidLimitKeyError("budget key, unit, and period do not match")
    return normalized_unit, normalized_period


def normalize_scope(scope_type: str, scope_id: uuid.UUID | None) -> tuple[str, uuid.UUID]:
    normalized_type = normalize_scope_type(scope_type)
    if scope_id is None:
        raise InvalidLimitScopeError(f"{normalized_type} limits require a scope id")
    return normalized_type, scope_id


def public_scope_id(scope_type: str, scope_id: uuid.UUID) -> uuid.UUID | None:
    return scope_id


def limit_response(limit: ResourceLimit) -> ResourceLimitRead:
    return ResourceLimitRead(
        id=limit.id,
        scopeType=limit.scope_type,
        scopeId=public_scope_id(limit.scope_type, limit.scope_id),
        limitKey=limit.limit_key,
        value=limit.value,
        createdAt=limit.created_at,
        updatedAt=limit.updated_at,
    )


def normalize_model_filter(value: str | None) -> str:
    return value.strip() if value else ""


def usage_budget_response(budget) -> UsageBudgetRead:
    return UsageBudgetRead(
        id=budget.id,
        scopeType=budget.scope_type,
        scopeId=budget.scope_id,
        budgetKey=budget.budget_key,
        value=budget.value,
        unit=budget.unit,
        period=budget.period,
        periodAnchor=budget.period_anchor,
        modelFilter=budget.model_filter,
        createdAt=budget.created_at,
        updatedAt=budget.updated_at,
    )


async def list_resource_limits(
    session: AsyncSession,
    user: User,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    limit_key: str | None = None,
) -> ResourceLimitListResponse:
    require_limits_admin(user)
    normalized_scope_type = None
    normalized_scope_id = None
    if scope_type is not None:
        normalized_scope_type = normalize_scope_type(scope_type)
        if scope_id is not None:
            normalized_scope_id = scope_id
    limits = await repository.list_limits(
        session,
        scope_type=normalized_scope_type,
        scope_id=normalized_scope_id,
        limit_key=normalize_limit_key(limit_key) if limit_key is not None else None,
    )
    return ResourceLimitListResponse(limits=[limit_response(limit) for limit in limits])


async def upsert_resource_limit(
    session: AsyncSession,
    user: User,
    payload: ResourceLimitUpsert,
) -> ResourceLimitRead:
    require_limits_admin(user)
    scope_type, scope_id = normalize_scope(payload.scope_type, payload.scope_id)
    limit_key = normalize_limit_key(payload.limit_key)
    limit = await repository.upsert_resource_limit(
        session,
        scope_type=scope_type,
        scope_id=scope_id,
        limit_key=limit_key,
        value=payload.value,
    )
    return limit_response(limit)


async def delete_resource_limit(
    session: AsyncSession,
    user: User,
    limit_id: uuid.UUID,
) -> None:
    require_limits_admin(user)
    limit = await repository.get_limit_by_id(session, limit_id)
    if limit is None:
        raise LimitNotFoundError("limit not found")
    await session.delete(limit)
    await session.flush()


async def list_usage_budgets(
    session: AsyncSession,
    user: User,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    budget_key: str | None = None,
) -> UsageBudgetListResponse:
    require_limits_admin(user)
    normalized_scope_type = None
    if scope_type is not None:
        normalized_scope_type = normalize_usage_budget_scope_type(scope_type)
    budgets = await repository.list_usage_budgets(
        session,
        scope_type=normalized_scope_type,
        scope_id=scope_id,
        budget_key=normalize_usage_budget_key(budget_key) if budget_key is not None else None,
    )
    return UsageBudgetListResponse(budgets=[usage_budget_response(budget) for budget in budgets])


async def upsert_usage_budget(
    session: AsyncSession,
    user: User,
    payload: UsageBudgetUpsert,
) -> UsageBudgetRead:
    require_limits_admin(user)
    scope_type = normalize_usage_budget_scope_type(payload.scope_type)
    budget_key = normalize_usage_budget_key(payload.budget_key)
    unit, period = usage_budget_unit_period(budget_key, payload.unit, payload.period)
    model_filter = normalize_model_filter(payload.model_filter)
    budget = await repository.upsert_usage_budget(
        session,
        scope_type=scope_type,
        scope_id=payload.scope_id,
        budget_key=budget_key,
        value=payload.value,
        unit=unit,
        period=period,
        period_anchor=payload.period_anchor,
        model_filter=model_filter,
    )
    return usage_budget_response(budget)


async def delete_usage_budget(
    session: AsyncSession,
    user: User,
    budget_id: uuid.UUID,
) -> None:
    require_limits_admin(user)
    budget = await repository.get_usage_budget_by_id(session, budget_id)
    if budget is None:
        raise LimitNotFoundError("usage budget not found")
    await session.delete(budget)
    await session.flush()


async def effective_limit(
    session: AsyncSession,
    *,
    limit_key: str,
    scope_chain: Iterable[tuple[str, uuid.UUID | None]],
) -> ResourceLimit | None:
    normalized_key = normalize_limit_key(limit_key)
    for scope_type, scope_id in scope_chain:
        normalized_type, normalized_id = normalize_scope(scope_type, scope_id)
        limit = await repository.get_limit(
            session,
            scope_type=normalized_type,
            scope_id=normalized_id,
            limit_key=normalized_key,
        )
        if limit is not None:
            return limit
    return None


async def require_limit_available(
    session: AsyncSession,
    *,
    limit_key: str,
    scope_chain: Iterable[tuple[str, uuid.UUID | None]],
    current_count: int,
    requested: int = 1,
) -> None:
    limit = await effective_limit(session, limit_key=limit_key, scope_chain=scope_chain)
    if limit is None:
        return
    if current_count + requested > limit.value:
        raise LimitExceededError(
            f"{limit.limit_key} limit exceeded: {current_count}/{limit.value}"
        )


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def add_month(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year
    if month > 12:
        month = 1
        year += 1
    days_by_month = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    day = min(value.day, days_by_month[month - 1])
    return value.replace(year=year, month=month, day=day)


def usage_budget_window(
    *,
    period: str,
    now: datetime,
    period_anchor: datetime | None = None,
) -> tuple[datetime, datetime]:
    now = ensure_aware_utc(now)
    if period_anchor is None:
        if period == "hour":
            start = now.replace(minute=0, second=0, microsecond=0)
            return start, start + timedelta(hours=1)
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, add_month(start)

    anchor = ensure_aware_utc(period_anchor)
    if period == "hour":
        delta = timedelta(hours=1)
        if now < anchor:
            return anchor, anchor + delta
        windows = int((now - anchor).total_seconds() // delta.total_seconds())
        start = anchor + windows * delta
        return start, start + delta
    if period == "day":
        delta = timedelta(days=1)
        if now < anchor:
            return anchor, anchor + delta
        windows = int((now - anchor).total_seconds() // delta.total_seconds())
        start = anchor + windows * delta
        return start, start + delta

    start = anchor
    if now < start:
        return start, add_month(start)
    next_start = add_month(start)
    while next_start <= now:
        start = next_start
        next_start = add_month(start)
    return start, next_start


def llm_budget_scope_chain(context: LLMBudgetContext) -> list[tuple[str, uuid.UUID]]:
    chain = [
        ("organization", context.organization_id),
        ("workspace", context.workspace_id),
    ]
    if context.user_id is not None:
        chain.append(("user", context.user_id))
    if context.agent_id is not None:
        chain.append(("agent", context.agent_id))
    return chain


async def require_llm_budget_available(
    session: AsyncSession,
    context: LLMBudgetContext,
) -> None:
    model = context.model.strip()
    budgets = await repository.list_usage_budgets_for_scopes(
        session,
        scope_chain=llm_budget_scope_chain(context),
        model=model,
    )
    now = context.now or datetime.now(UTC)
    for budget in budgets:
        window_start, window_end = usage_budget_window(
            period=budget.period,
            now=now,
            period_anchor=budget.period_anchor,
        )
        spend = await repository.llm_usage_budget_spend(
            session,
            budget=budget,
            window_start=window_start,
            window_end=window_end,
        )
        if spend >= Decimal(budget.value):
            model_detail = f" for model {budget.model_filter}" if budget.model_filter else ""
            raise LimitExceededError(
                f"{budget.budget_key}{model_detail} budget exhausted: "
                f"{spend}/{budget.value}"
            )
