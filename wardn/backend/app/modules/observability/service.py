from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability import repository
from app.modules.observability.models import LLMModelPrice, LLMTrace, LLMUsageRecord
from app.modules.observability.schemas import (
    LLMModelPriceCreate,
    LLMModelPriceListResponse,
    LLMModelPriceRead,
    LLMModelPriceUpdate,
    LLMUsageListResponse,
    LLMUsageRead,
    LLMUsageSummary,
    MCPToolUsageListResponse,
    MCPToolUsageRead,
    MCPToolUsageSummary,
)
from app.modules.users.models import User

TOKEN_PRICE_DIVISOR = Decimal("1000000")


class DuplicateLLMModelPriceError(ValueError):
    pass


class LLMModelPriceNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class LLMTokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    response_model: str = ""


def decimal_price(value: Decimal | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def token_cost(tokens: int, price_per_1m: Decimal | int | str | None) -> Decimal:
    if tokens <= 0:
        return Decimal("0")
    return (Decimal(tokens) * decimal_price(price_per_1m)) / TOKEN_PRICE_DIVISOR


def calculate_llm_cost(price: LLMModelPrice | None, usage: LLMTokenUsage) -> Decimal:
    if price is None:
        return Decimal("0")

    cache_read_tokens = max(usage.cache_read_input_tokens, 0)
    cache_write_tokens = max(usage.cache_write_input_tokens, 0)
    standard_input_tokens = max(
        usage.input_tokens - cache_read_tokens - cache_write_tokens,
        0,
    )
    cost = token_cost(standard_input_tokens, price.input_usd_per_1m_tokens)
    cost += token_cost(usage.output_tokens, price.output_usd_per_1m_tokens)
    cost += token_cost(
        cache_read_tokens,
        price.cache_read_usd_per_1m_tokens
        if price.cache_read_usd_per_1m_tokens is not None
        else price.input_usd_per_1m_tokens,
    )
    cost += token_cost(
        cache_write_tokens,
        price.cache_write_usd_per_1m_tokens
        if price.cache_write_usd_per_1m_tokens is not None
        else price.input_usd_per_1m_tokens,
    )
    return cost.quantize(Decimal("0.0000000001"))


async def record_llm_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    user_id: UUID | None,
    agent_id: UUID | None,
    agent_run_id: UUID | None,
    provider: str,
    model: str,
    usage: LLMTokenUsage,
    started_at: datetime,
    finished_at: datetime | None,
    status: str,
    trace_id: str = "",
    span_id: str = "",
    error: str = "",
) -> LLMUsageRecord:
    price = await repository.get_model_price(session, provider=provider, model=model)
    cost = calculate_llm_cost(price, usage)
    trace = LLMTrace(
        trace_id=trace_id,
        span_id=span_id,
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens or usage.input_tokens + usage.output_tokens,
        estimated_cost_usd=cost,
    )
    usage_record = LLMUsageRecord(
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        provider=provider,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        trace_id=trace_id,
        span_id=span_id,
        error=error,
    )
    return await repository.create_llm_usage_record(
        session,
        usage_record=usage_record,
        trace=trace,
    )


def normalize_provider(value: str) -> str:
    return value.strip().casefold()


def normalize_model(value: str) -> str:
    return value.strip()


def model_price_read(model_price: LLMModelPrice) -> LLMModelPriceRead:
    return LLMModelPriceRead(
        id=model_price.id,
        provider=model_price.provider,
        model=model_price.model,
        inputUsdPer1mTokens=model_price.input_usd_per_1m_tokens,
        outputUsdPer1mTokens=model_price.output_usd_per_1m_tokens,
        cacheReadUsdPer1mTokens=model_price.cache_read_usd_per_1m_tokens,
        cacheWriteUsdPer1mTokens=model_price.cache_write_usd_per_1m_tokens,
        createdAt=model_price.created_at,
        updatedAt=model_price.updated_at,
    )


async def list_llm_model_prices(session: AsyncSession) -> LLMModelPriceListResponse:
    return LLMModelPriceListResponse(
        prices=[
            model_price_read(model_price)
            for model_price in await repository.list_model_prices(session)
        ]
    )


async def create_llm_model_price(
    session: AsyncSession,
    payload: LLMModelPriceCreate,
) -> LLMModelPriceRead:
    provider = normalize_provider(payload.provider)
    model = normalize_model(payload.model)
    existing = await repository.get_model_price(session, provider=provider, model=model)
    if existing is not None:
        raise DuplicateLLMModelPriceError("model price already exists")

    model_price = LLMModelPrice(
        provider=provider,
        model=model,
        input_usd_per_1m_tokens=payload.input_usd_per_1m_tokens,
        output_usd_per_1m_tokens=payload.output_usd_per_1m_tokens,
        cache_read_usd_per_1m_tokens=payload.cache_read_usd_per_1m_tokens,
        cache_write_usd_per_1m_tokens=payload.cache_write_usd_per_1m_tokens,
    )
    return model_price_read(
        await repository.save_model_price(session, model_price=model_price)
    )


async def update_llm_model_price(
    session: AsyncSession,
    *,
    price_id: UUID,
    payload: LLMModelPriceUpdate,
) -> LLMModelPriceRead:
    model_price = await repository.get_model_price_by_id(session, price_id=price_id)
    if model_price is None:
        raise LLMModelPriceNotFoundError("model price not found")

    update_values = payload.model_dump(exclude_unset=True, by_alias=False)
    next_provider = normalize_provider(update_values.get("provider", model_price.provider))
    next_model = normalize_model(update_values.get("model", model_price.model))
    duplicate = await repository.get_model_price(
        session,
        provider=next_provider,
        model=next_model,
    )
    if duplicate is not None and duplicate.id != model_price.id:
        raise DuplicateLLMModelPriceError("model price already exists")

    model_price.provider = next_provider
    model_price.model = next_model
    if "input_usd_per_1m_tokens" in update_values:
        model_price.input_usd_per_1m_tokens = update_values["input_usd_per_1m_tokens"]
    if "output_usd_per_1m_tokens" in update_values:
        model_price.output_usd_per_1m_tokens = update_values["output_usd_per_1m_tokens"]
    if "cache_read_usd_per_1m_tokens" in update_values:
        model_price.cache_read_usd_per_1m_tokens = update_values[
            "cache_read_usd_per_1m_tokens"
        ]
    if "cache_write_usd_per_1m_tokens" in update_values:
        model_price.cache_write_usd_per_1m_tokens = update_values[
            "cache_write_usd_per_1m_tokens"
        ]

    return model_price_read(
        await repository.save_model_price(session, model_price=model_price)
    )


async def delete_llm_model_price(
    session: AsyncSession,
    *,
    price_id: UUID,
) -> None:
    model_price = await repository.get_model_price_by_id(session, price_id=price_id)
    if model_price is None:
        raise LLMModelPriceNotFoundError("model price not found")
    await repository.delete_model_price(session, model_price=model_price)


def user_display_name(user: User | None) -> str:
    return user.display_name if user is not None else ""


def llm_usage_read(
    usage_record: LLMUsageRecord,
    user: User | None,
    agent: Agent | None,
) -> LLMUsageRead:
    return LLMUsageRead(
        id=usage_record.id,
        organizationId=usage_record.organization_id,
        workspaceId=usage_record.workspace_id,
        userId=usage_record.user_id,
        userEmail=user.email if user is not None else "",
        userDisplayName=user_display_name(user),
        agentId=usage_record.agent_id,
        agentName=agent.name if agent is not None else "",
        agentRunId=usage_record.agent_run_id,
        provider=usage_record.provider,
        model=usage_record.model,
        inputTokens=usage_record.input_tokens,
        outputTokens=usage_record.output_tokens,
        totalTokens=usage_record.input_tokens + usage_record.output_tokens,
        costUsd=usage_record.cost_usd,
        startedAt=usage_record.started_at,
        finishedAt=usage_record.finished_at,
        status=usage_record.status,
        traceId=usage_record.trace_id,
        spanId=usage_record.span_id,
        error=usage_record.error,
    )


def llm_usage_summary(records: list[LLMUsageRecord]) -> LLMUsageSummary:
    failed = sum(1 for record in records if record.status == "failed")
    total_input_tokens = sum(record.input_tokens for record in records)
    total_output_tokens = sum(record.output_tokens for record in records)
    return LLMUsageSummary(
        totalCalls=len(records),
        succeeded=sum(1 for record in records if record.status == "succeeded"),
        failed=failed,
        running=sum(1 for record in records if record.status == "running"),
        inputTokens=total_input_tokens,
        outputTokens=total_output_tokens,
        totalTokens=total_input_tokens + total_output_tokens,
        totalCostUsd=sum((record.cost_usd for record in records), Decimal("0")),
        attributed=sum(
            1
            for record in records
            if record.user_id is not None
            or record.agent_id is not None
            or record.agent_run_id is not None
        ),
        unattributed=sum(
            1
            for record in records
            if record.user_id is None
            and record.agent_id is None
            and record.agent_run_id is None
        ),
    )


def tool_usage_read(
    invocation: MCPToolInvocation,
    user: User | None,
    agent: Agent | None,
) -> MCPToolUsageRead:
    return MCPToolUsageRead(
        id=invocation.id,
        organizationId=invocation.organization_id,
        workspaceId=invocation.workspace_id,
        runtimeSessionId=invocation.runtime_session_id,
        installationId=invocation.installation_id,
        userId=invocation.user_id,
        userEmail=user.email if user is not None else "",
        userDisplayName=user_display_name(user),
        agentId=invocation.agent_id,
        agentName=agent.name if agent is not None else "",
        agentRunId=invocation.agent_run_id,
        serverName=invocation.server_name,
        serverVersion=invocation.server_version,
        toolName=invocation.tool_name,
        status=invocation.status,
        startedAt=invocation.started_at,
        finishedAt=invocation.finished_at,
        durationMs=invocation.duration_ms,
        inputSizeBytes=invocation.input_size_bytes,
        outputSizeBytes=invocation.output_size_bytes,
        isError=invocation.is_error,
        error=invocation.error,
    )


def tool_usage_summary(invocations: list[MCPToolInvocation]) -> MCPToolUsageSummary:
    total = len(invocations)
    completed_durations = [
        invocation.duration_ms
        for invocation in invocations
        if invocation.duration_ms is not None and invocation.duration_ms >= 0
    ]
    average_duration_ms = (
        round(sum(completed_durations) / len(completed_durations))
        if completed_durations
        else None
    )
    failed = sum(
        1
        for invocation in invocations
        if invocation.status == "failed" or invocation.is_error
    )
    return MCPToolUsageSummary(
        total=total,
        succeeded=sum(
            1
            for invocation in invocations
            if invocation.status == "succeeded" and not invocation.is_error
        ),
        failed=failed,
        running=sum(1 for invocation in invocations if invocation.status == "running"),
        attributed=sum(
            1
            for invocation in invocations
            if invocation.user_id is not None
            or invocation.agent_id is not None
            or invocation.agent_run_id is not None
        ),
        unattributed=sum(
            1
            for invocation in invocations
            if invocation.user_id is None
            and invocation.agent_id is None
            and invocation.agent_run_id is None
        ),
        averageDurationMs=average_duration_ms,
    )


async def list_workspace_mcp_tool_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int = 100,
) -> MCPToolUsageListResponse:
    rows = await repository.list_mcp_tool_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
    )
    invocations = [invocation for invocation, _user, _agent in rows]
    return MCPToolUsageListResponse(
        summary=tool_usage_summary(invocations),
        toolCalls=[
            tool_usage_read(invocation, user, agent)
            for invocation, user, agent in rows
        ],
    )


async def list_workspace_llm_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int = 100,
) -> LLMUsageListResponse:
    rows = await repository.list_llm_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
    )
    records = [usage_record for usage_record, _user, _agent in rows]
    return LLMUsageListResponse(
        summary=llm_usage_summary(records),
        records=[
            llm_usage_read(usage_record, user, agent)
            for usage_record, user, agent in rows
        ],
    )
