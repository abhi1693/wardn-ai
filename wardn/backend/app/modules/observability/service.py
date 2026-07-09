from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability import repository
from app.modules.observability.models import LLMModelPrice, LLMTrace, LLMUsageRecord
from app.modules.observability.schemas import (
    LLMModelPriceCreate,
    LLMModelPriceListResponse,
    LLMModelPricePrefillResponse,
    LLMModelPriceRead,
    LLMModelPriceUpdate,
    LLMUsageListResponse,
    LLMUsageRead,
    LLMUsageSummary,
    MCPToolUsageListResponse,
    MCPToolUsageRead,
    MCPToolUsageSummary,
    UsageSummaryBreakdownRow,
    UsageSummaryResponse,
    UsageSummaryTotals,
    UsageTrendPoint,
)
from app.modules.users.models import User

TOKEN_PRICE_DIVISOR = Decimal("1000000")
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_TIMEOUT_SECONDS = 10
OPENROUTER_PROVIDER_SLUGS = {
    "openai": "openai",
    "openai_chatgpt": "openai",
}


class DuplicateLLMModelPriceError(ValueError):
    pass


class LLMModelPriceNotFoundError(ValueError):
    pass


class LLMModelPricePrefillError(ValueError):
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


def price_per_token_to_per_1m(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return (Decimal(str(value)) * TOKEN_PRICE_DIVISOR).quantize(Decimal("0.0000000001"))
    except Exception as exc:
        raise LLMModelPricePrefillError("OpenRouter returned invalid pricing data") from exc


def openrouter_provider_slug(provider: str) -> str:
    normalized_provider = normalize_provider(provider)
    return OPENROUTER_PROVIDER_SLUGS.get(normalized_provider, normalized_provider)


def openrouter_model_candidates(provider: str, model: str) -> set[str]:
    provider_slug = openrouter_provider_slug(provider)
    normalized_model = normalize_model(model).casefold()
    candidates = {
        normalized_model,
        f"{provider_slug}/{normalized_model}",
    }
    if "/" in normalized_model:
        candidates.add(normalized_model.split("/", 1)[1])
    return {candidate for candidate in candidates if candidate}


def openrouter_entry_matches_model(entry: dict[str, Any], provider: str, model: str) -> bool:
    provider_slug = openrouter_provider_slug(provider)
    normalized_model = normalize_model(model).casefold()
    candidates = openrouter_model_candidates(provider, model)
    for key in ("id", "canonical_slug"):
        value = str(entry.get(key) or "").casefold()
        if not value:
            continue
        if value in candidates:
            return True
        if value.startswith(f"{provider_slug}/") and value.split("/", 1)[1] == normalized_model:
            return True
    return False


def openrouter_prefill_response(
    *,
    provider: str,
    model: str,
    entry: dict[str, Any] | None,
) -> LLMModelPricePrefillResponse:
    if entry is None:
        return LLMModelPricePrefillResponse(
            found=False,
            provider=normalize_provider(provider),
            model=normalize_model(model),
        )

    pricing = entry.get("pricing")
    if not isinstance(pricing, dict):
        raise LLMModelPricePrefillError("OpenRouter returned invalid pricing data")

    return LLMModelPricePrefillResponse(
        found=True,
        provider=normalize_provider(provider),
        model=normalize_model(model),
        inputUsdPer1mTokens=price_per_token_to_per_1m(pricing.get("prompt")),
        outputUsdPer1mTokens=price_per_token_to_per_1m(pricing.get("completion")),
        cacheReadUsdPer1mTokens=price_per_token_to_per_1m(pricing.get("input_cache_read")),
        cacheWriteUsdPer1mTokens=price_per_token_to_per_1m(pricing.get("input_cache_write")),
        source="openrouter",
        sourceModelId=str(entry.get("id") or ""),
        sourceModelName=str(entry.get("name") or ""),
    )


async def fetch_openrouter_model_prices(
    *,
    provider: str,
    model: str,
) -> LLMModelPricePrefillResponse:
    try:
        async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT_SECONDS) as client:
            response = await client.get(OPENROUTER_MODELS_URL)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMModelPricePrefillError("OpenRouter pricing could not be loaded") from exc

    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise LLMModelPricePrefillError("OpenRouter returned invalid model data")

    matched_entry = next(
        (
            entry
            for entry in data
            if isinstance(entry, dict) and openrouter_entry_matches_model(entry, provider, model)
        ),
        None,
    )
    return openrouter_prefill_response(provider=provider, model=model, entry=matched_entry)


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


def row_value(row, key: str, default=0):
    return row._mapping.get(key, default)


def usage_totals_response(row, *, tool_calls: int) -> UsageSummaryTotals:
    input_tokens = int(row_value(row, "input_tokens"))
    output_tokens = int(row_value(row, "output_tokens"))
    return UsageSummaryTotals(
        requests=int(row_value(row, "requests")),
        succeeded=int(row_value(row, "succeeded")),
        failed=int(row_value(row, "failed")),
        running=int(row_value(row, "running")),
        inputTokens=input_tokens,
        outputTokens=output_tokens,
        totalTokens=input_tokens + output_tokens,
        costUsd=row_value(row, "cost_usd", Decimal("0")) or Decimal("0"),
        toolCalls=tool_calls,
    )


def display_label(*, name: str | None = None, email: str | None = None, fallback: str) -> str:
    value = (name or "").strip() or (email or "").strip()
    return value or fallback


def person_label(first_name: str | None, last_name: str | None, email: str | None) -> str:
    full_name = f"{first_name or ''} {last_name or ''}".strip()
    return display_label(name=full_name, email=email, fallback="Unattributed user")


def bucket_id(value: UUID | str | None, fallback: str) -> str:
    return str(value) if value is not None else fallback


def add_llm_breakdown(
    buckets: dict[str, dict[str, Any]],
    *,
    key: str,
    label: str,
    row,
) -> None:
    input_tokens = int(row_value(row, "input_tokens"))
    output_tokens = int(row_value(row, "output_tokens"))
    bucket = buckets.setdefault(
        key,
        {
            "id": key,
            "label": label,
            "requests": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "costUsd": Decimal("0"),
            "toolCalls": 0,
        },
    )
    bucket["label"] = label
    bucket["requests"] += int(row_value(row, "requests"))
    bucket["inputTokens"] += input_tokens
    bucket["outputTokens"] += output_tokens
    bucket["costUsd"] += row_value(row, "cost_usd", Decimal("0")) or Decimal("0")


def add_tool_breakdown(
    buckets: dict[str, dict[str, Any]],
    *,
    key: str,
    label: str,
    tool_calls: int,
) -> None:
    bucket = buckets.setdefault(
        key,
        {
            "id": key,
            "label": label,
            "requests": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "costUsd": Decimal("0"),
            "toolCalls": 0,
        },
    )
    if not bucket["label"] or bucket["label"].startswith("Unattributed"):
        bucket["label"] = label
    bucket["toolCalls"] += tool_calls


def breakdown_rows(buckets: dict[str, dict[str, Any]]) -> list[UsageSummaryBreakdownRow]:
    rows = [
        UsageSummaryBreakdownRow(
            id=str(bucket["id"]),
            label=str(bucket["label"]),
            requests=int(bucket["requests"]),
            inputTokens=int(bucket["inputTokens"]),
            outputTokens=int(bucket["outputTokens"]),
            totalTokens=int(bucket["inputTokens"]) + int(bucket["outputTokens"]),
            costUsd=bucket["costUsd"],
            toolCalls=int(bucket["toolCalls"]),
        )
        for bucket in buckets.values()
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.cost_usd,
            row.requests,
            row.tool_calls,
            row.total_tokens,
            row.label.casefold(),
        ),
        reverse=True,
    )


def usage_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def add_llm_daily(
    buckets: dict[date, dict[str, Any]],
    *,
    row,
) -> None:
    point_date = usage_date(row[0])
    bucket = buckets.setdefault(
        point_date,
        {
            "date": point_date,
            "requests": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "costUsd": Decimal("0"),
            "toolCalls": 0,
        },
    )
    bucket["requests"] += int(row_value(row, "requests"))
    bucket["inputTokens"] += int(row_value(row, "input_tokens"))
    bucket["outputTokens"] += int(row_value(row, "output_tokens"))
    bucket["costUsd"] += row_value(row, "cost_usd", Decimal("0")) or Decimal("0")


def add_tool_daily(
    buckets: dict[date, dict[str, Any]],
    *,
    point_date: date,
    tool_calls: int,
) -> None:
    bucket = buckets.setdefault(
        point_date,
        {
            "date": point_date,
            "requests": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "costUsd": Decimal("0"),
            "toolCalls": 0,
        },
    )
    bucket["toolCalls"] += tool_calls


def trend_points(buckets: dict[date, dict[str, Any]]) -> list[UsageTrendPoint]:
    return [
        UsageTrendPoint(
            date=point_date,
            requests=int(bucket["requests"]),
            inputTokens=int(bucket["inputTokens"]),
            outputTokens=int(bucket["outputTokens"]),
            totalTokens=int(bucket["inputTokens"]) + int(bucket["outputTokens"]),
            costUsd=bucket["costUsd"],
            toolCalls=int(bucket["toolCalls"]),
        )
        for point_date, bucket in sorted(buckets.items(), key=lambda item: item[0])
    ]


async def usage_summary_response(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> UsageSummaryResponse:
    totals_row = await repository.llm_usage_totals(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    total_tool_calls = await repository.mcp_tool_call_count(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    by_user: dict[str, dict[str, Any]] = {}
    for row in await repository.llm_usage_by_user(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_llm_breakdown(
            by_user,
            key=bucket_id(row[0], "unattributed"),
            label=person_label(row[1], row[2], row[3]),
            row=row,
        )
    for row in await repository.mcp_tool_calls_by_user(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_tool_breakdown(
            by_user,
            key=bucket_id(row[0], "unattributed"),
            label=person_label(row[1], row[2], row[3]),
            tool_calls=int(row[4] or 0),
        )

    by_workspace: dict[str, dict[str, Any]] = {}
    for row in await repository.llm_usage_by_workspace(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_llm_breakdown(
            by_workspace,
            key=bucket_id(row[0], "unknown-workspace"),
            label=display_label(name=row[1], fallback="Unknown workspace"),
            row=row,
        )
    for row in await repository.mcp_tool_calls_by_workspace(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_tool_breakdown(
            by_workspace,
            key=bucket_id(row[0], "unknown-workspace"),
            label=display_label(name=row[1], fallback="Unknown workspace"),
            tool_calls=int(row[2] or 0),
        )

    by_agent: dict[str, dict[str, Any]] = {}
    for row in await repository.llm_usage_by_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_llm_breakdown(
            by_agent,
            key=bucket_id(row[0], "unattributed-agent"),
            label=display_label(name=row[1], fallback="Unattributed agent"),
            row=row,
        )
    for row in await repository.mcp_tool_calls_by_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_tool_breakdown(
            by_agent,
            key=bucket_id(row[0], "unattributed-agent"),
            label=display_label(name=row[1], fallback="Unattributed agent"),
            tool_calls=int(row[2] or 0),
        )

    by_model: dict[str, dict[str, Any]] = {}
    for row in await repository.llm_usage_by_model(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        provider = str(row[0])
        model = str(row[1])
        add_llm_breakdown(
            by_model,
            key=f"{provider}:{model}",
            label=f"{provider} / {model}",
            row=row,
        )

    daily: dict[date, dict[str, Any]] = {}
    for row in await repository.llm_usage_by_day(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_llm_daily(daily, row=row)
    for row in await repository.mcp_tool_calls_by_day(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
    ):
        add_tool_daily(daily, point_date=usage_date(row[0]), tool_calls=int(row[1] or 0))

    return UsageSummaryResponse(
        summary=usage_totals_response(totals_row, tool_calls=total_tool_calls),
        byUser=breakdown_rows(by_user),
        byWorkspace=breakdown_rows(by_workspace),
        byAgent=breakdown_rows(by_agent),
        byModel=breakdown_rows(by_model),
        daily=trend_points(daily),
    )


async def organization_usage_summary(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> UsageSummaryResponse:
    return await usage_summary_response(session, organization_id=organization_id)


async def workspace_usage_summary(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
) -> UsageSummaryResponse:
    return await usage_summary_response(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


async def user_usage_summary(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> UsageSummaryResponse:
    return await usage_summary_response(session, user_id=user_id)


async def agent_run_usage_summary(
    session: AsyncSession,
    *,
    agent_run_id: UUID,
) -> UsageSummaryTotals:
    totals_row = await repository.llm_usage_totals(session, agent_run_id=agent_run_id)
    total_tool_calls = await repository.mcp_tool_call_count(
        session,
        agent_run_id=agent_run_id,
    )
    return usage_totals_response(totals_row, tool_calls=total_tool_calls)


async def agent_run_trace_ids(
    session: AsyncSession,
    *,
    agent_run_id: UUID,
) -> tuple[str, str]:
    records = await repository.list_llm_usage_records_for_agent_run(
        session,
        agent_run_id=agent_run_id,
    )
    for record in records:
        if record.trace_id:
            return record.trace_id, record.span_id
    return "", ""


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
