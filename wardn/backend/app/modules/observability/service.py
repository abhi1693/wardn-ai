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
    MCPToolUsageListResponse,
    MCPToolUsageRead,
    MCPToolUsageSummary,
)
from app.modules.users.models import User

TOKEN_PRICE_DIVISOR = Decimal("1000000")


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


def user_display_name(user: User | None) -> str:
    return user.display_name if user is not None else ""


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
