from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
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
    OrganizationDashboardAttentionItem,
    OrganizationDashboardCatalogHealth,
    OrganizationDashboardProviderRow,
    OrganizationDashboardResponse,
    OrganizationDashboardRuntimeRow,
    OrganizationDashboardSummary,
    OrganizationDashboardToolRow,
    OrganizationDashboardWorkspaceRow,
    UsageSummaryBreakdownRow,
    UsageSummaryResponse,
    UsageSummaryTotals,
    UsageSummaryWindow,
    UsageTrendPoint,
    WorkspaceObservabilityAgentRunRow,
    WorkspaceObservabilityAttentionItem,
    WorkspaceObservabilityDashboardResponse,
    WorkspaceObservabilityDashboardSummary,
    WorkspaceObservabilityTopToolRow,
)
from app.modules.users.models import User

TOKEN_PRICE_DIVISOR = Decimal("1000000")
USAGE_SUMMARY_DEFAULT_DAYS = 30
USAGE_SUMMARY_MAX_DAYS = 366
USAGE_SUMMARY_DEFAULT_BREAKDOWN_LIMIT = 25
USAGE_SUMMARY_MAX_BREAKDOWN_LIMIT = 100
DASHBOARD_CATALOG_STALE_AFTER = timedelta(hours=24)
DASHBOARD_DEFAULT_LIMIT = 8
DASHBOARD_MAX_LIMIT = 100
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_TIMEOUT_SECONDS = 10
OPENROUTER_MAX_MODEL_PAGES = 20
OPENROUTER_PROVIDER_SLUGS = {
    "anthropic": "anthropic",
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
class ResolvedUsageSummaryWindow:
    start_date: date
    end_date: date
    started_at_from: datetime
    started_at_to: datetime


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


async def fetch_openrouter_model_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    next_url = OPENROUTER_MODELS_URL
    seen_urls: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT_SECONDS) as client:
            for _ in range(OPENROUTER_MAX_MODEL_PAGES):
                if not next_url or next_url in seen_urls:
                    break
                seen_urls.add(next_url)
                response = await client.get(next_url)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise LLMModelPricePrefillError(
                        "OpenRouter returned invalid model data"
                    ) from exc
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, list):
                    raise LLMModelPricePrefillError("OpenRouter returned invalid model data")
                entries.extend(entry for entry in data if isinstance(entry, dict))

                links = payload.get("links") if isinstance(payload, dict) else None
                next_link = links.get("next") if isinstance(links, dict) else None
                next_url = (
                    urljoin(OPENROUTER_MODELS_URL, next_link.strip())
                    if isinstance(next_link, str) and next_link.strip()
                    else ""
                )
    except httpx.HTTPError as exc:
        raise LLMModelPricePrefillError("OpenRouter pricing could not be loaded") from exc
    return entries


def openrouter_model_price_create(
    *,
    provider: str,
    model: str,
    entry: dict[str, Any],
) -> LLMModelPriceCreate | None:
    response = openrouter_prefill_response(provider=provider, model=model, entry=entry)
    if response.input_usd_per_1m_tokens is None or response.output_usd_per_1m_tokens is None:
        return None
    return LLMModelPriceCreate(
        provider=response.provider,
        model=response.model,
        inputUsdPer1mTokens=response.input_usd_per_1m_tokens,
        outputUsdPer1mTokens=response.output_usd_per_1m_tokens,
        cacheReadUsdPer1mTokens=response.cache_read_usd_per_1m_tokens,
        cacheWriteUsdPer1mTokens=response.cache_write_usd_per_1m_tokens,
    )


async def create_missing_openrouter_model_prices(
    session: AsyncSession,
    *,
    provider: str,
    models: list[str],
) -> int:
    normalized_provider = normalize_provider(provider)
    normalized_models = sorted(
        {normalized_model for model in models if (normalized_model := normalize_model(model))}
    )
    if not normalized_models:
        return 0

    existing = await repository.list_model_prices_for_provider_models(
        session,
        provider=normalized_provider,
        models=normalized_models,
    )
    existing_models = {model_price.model for model_price in existing}
    model_entries = await fetch_openrouter_model_entries()

    created_count = 0
    for model in normalized_models:
        if model in existing_models:
            continue
        matched_entry = next(
            (
                entry
                for entry in model_entries
                if openrouter_entry_matches_model(entry, normalized_provider, model)
            ),
            None,
        )
        if matched_entry is None:
            continue
        payload = openrouter_model_price_create(
            provider=normalized_provider,
            model=model,
            entry=matched_entry,
        )
        if payload is None:
            continue
        session.add(
            LLMModelPrice(
                provider=payload.provider,
                model=payload.model,
                input_usd_per_1m_tokens=payload.input_usd_per_1m_tokens,
                output_usd_per_1m_tokens=payload.output_usd_per_1m_tokens,
                cache_read_usd_per_1m_tokens=payload.cache_read_usd_per_1m_tokens,
                cache_write_usd_per_1m_tokens=payload.cache_write_usd_per_1m_tokens,
            )
        )
        created_count += 1

    if created_count:
        await session.flush()
    return created_count


async def fetch_openrouter_model_prices(
    *,
    provider: str,
    model: str,
) -> LLMModelPricePrefillResponse:
    data = await fetch_openrouter_model_entries()

    matched_entry = next(
        (
            entry
            for entry in data
            if openrouter_entry_matches_model(entry, provider, model)
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
    try:
        saved_model_price = await repository.save_model_price(
            session,
            model_price=model_price,
        )
    except IntegrityError as exc:
        if is_constraint_violation(exc, {"uq_llm_model_prices_provider_model"}):
            raise DuplicateLLMModelPriceError("model price already exists") from exc
        raise
    return model_price_read(saved_model_price)


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

    try:
        saved_model_price = await repository.save_model_price(
            session,
            model_price=model_price,
        )
    except IntegrityError as exc:
        if is_constraint_violation(exc, {"uq_llm_model_prices_provider_model"}):
            raise DuplicateLLMModelPriceError("model price already exists") from exc
        raise
    return model_price_read(saved_model_price)


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
    mapping = getattr(row, "_mapping", row)
    return mapping.get(key, default)


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


def breakdown_rows(
    buckets: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[UsageSummaryBreakdownRow]:
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
    )[:limit]


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
    point_date = usage_date(row_value(row, "usage_day"))
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


def resolve_usage_summary_window(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    today: date | None = None,
) -> ResolvedUsageSummaryWindow:
    effective_end = end_date or today or datetime.now(UTC).date()
    effective_start = start_date or effective_end - timedelta(days=USAGE_SUMMARY_DEFAULT_DAYS - 1)
    if effective_start > effective_end:
        raise ValueError("startDate must be on or before endDate")
    day_count = (effective_end - effective_start).days + 1
    if day_count > USAGE_SUMMARY_MAX_DAYS:
        raise ValueError(f"usage summary range cannot exceed {USAGE_SUMMARY_MAX_DAYS} days")
    return ResolvedUsageSummaryWindow(
        start_date=effective_start,
        end_date=effective_end,
        started_at_from=datetime.combine(effective_start, time.min, tzinfo=UTC),
        started_at_to=datetime.combine(
            effective_end + timedelta(days=1),
            time.min,
            tzinfo=UTC,
        ),
    )


def int_row_value(row, key: str, default: int = 0) -> int:
    return int(row_value(row, key, default) or default)


def decimal_row_value(row, key: str, default: Decimal | str = Decimal("0")) -> Decimal:
    value = row_value(row, key, default)
    return value if isinstance(value, Decimal) else Decimal(str(value or default))


def optional_duration(value: object) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((part / total) * 100, 1)


def success_rate(succeeded: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round((succeeded / total) * 100, 1)


def projected_monthly_cost(cost: Decimal, window: UsageSummaryWindow) -> Decimal:
    days = max((window.end_date - window.start_date).days + 1, 1)
    return ((cost * Decimal(30)) / Decimal(days)).quantize(Decimal("0.000001"))


def budget_utilization_percent(
    *,
    projected_cost: Decimal,
    monthly_budget: Decimal | None,
) -> float | None:
    if monthly_budget is None or monthly_budget <= 0:
        return None
    return round(float((projected_cost / monthly_budget) * Decimal(100)), 1)


def runtime_label(value: str) -> str:
    normalized = value.strip().casefold()
    labels = {
        "remote": "Remote endpoints",
        "oci": "OCI packages",
        "npm": "NPM packages",
        "uvx": "UVX packages",
        "metadata": "Metadata only",
    }
    return labels.get(normalized, value or "Unknown runtime")


def pluralize(value: int, singular: str, plural: str | None = None) -> str:
    return singular if value == 1 else plural or f"{singular}s"


def dashboard_health_score(
    *,
    control: dict[str, Any],
    usage: UsageSummaryResponse,
    tool_failed: int,
    tool_total: int,
    budget_percent: float | None,
) -> int:
    summary = usage.summary
    completed_requests = summary.succeeded + summary.failed
    score = 100
    inactive_workspaces = max(
        int_row_value(control, "workspaces") - int_row_value(control, "active_workspaces"),
        0,
    )
    score -= min(15, inactive_workspaces * 4)
    if int_row_value(control, "active_provider_credentials") == 0:
        score -= 18
    score -= min(20, int_row_value(control, "servers_needing_attention") * 5)
    score -= min(15, int_row_value(control, "runtime_sessions_needing_attention") * 5)
    score -= min(
        15,
        int_row_value(control, "catalog_errors") * 5
        + int_row_value(control, "stale_catalog_sources") * 2,
    )
    score -= min(20, int(percent(summary.failed, completed_requests) * 0.5))
    score -= min(15, int(percent(tool_failed, tool_total) * 0.4))
    if budget_percent is not None:
        if budget_percent >= 100:
            score -= 15
        elif budget_percent >= 80:
            score -= 8
    return max(min(score, 100), 0)


def dashboard_attention_items(
    *,
    control: dict[str, Any],
    usage: UsageSummaryResponse,
    tool_failed: int,
    budget_percent: float | None,
) -> list[OrganizationDashboardAttentionItem]:
    items: list[OrganizationDashboardAttentionItem] = []

    def add(key: str, label: str, detail: str, severity: str) -> None:
        items.append(
            OrganizationDashboardAttentionItem(
                key=key,
                label=label,
                detail=detail,
                severity=severity,
            )
        )

    if int_row_value(control, "active_provider_credentials") == 0:
        add(
            "provider-credentials",
            "No active model provider",
            "Agents cannot run reliably until at least one credential is active.",
            "danger",
        )
    servers_needing_attention = int_row_value(control, "servers_needing_attention")
    if servers_needing_attention:
        server_label = pluralize(servers_needing_attention, "server")
        add(
            "mcp-servers",
            f"{servers_needing_attention} MCP {server_label} need review",
            "Disabled installs or install errors are reducing tool availability.",
            "danger",
        )
    runtime_attention = int_row_value(control, "runtime_sessions_needing_attention")
    if runtime_attention:
        add(
            "runtime-sessions",
            f"{runtime_attention} runtime {pluralize(runtime_attention, 'session')} need review",
            "Runtime failures can make installed servers appear available but fail at call time.",
            "warning",
        )
    if usage.summary.failed:
        add(
            "llm-failures",
            f"{usage.summary.failed} failed model {pluralize(usage.summary.failed, 'request')}",
            "Review recent runs for provider errors, model limits, or invalid payloads.",
            "warning",
        )
    if tool_failed:
        add(
            "tool-failures",
            f"{tool_failed} failed MCP tool {pluralize(tool_failed, 'call')}",
            "Tool errors are visible in observability and can point to schema or auth issues.",
            "warning",
        )
    catalog_errors = int_row_value(control, "catalog_errors")
    if catalog_errors:
        add(
            "catalog-errors",
            f"{catalog_errors} catalog {pluralize(catalog_errors, 'source')} reporting errors",
            "Catalog errors can hide new versions and server metadata.",
            "warning",
        )
    stale_catalog_sources = int_row_value(control, "stale_catalog_sources")
    if stale_catalog_sources:
        add(
            "catalog-stale",
            f"{stale_catalog_sources} catalog {pluralize(stale_catalog_sources, 'source')} stale",
            "Enabled sources have not synced successfully in the expected window.",
            "info",
        )
    server_updates = int_row_value(control, "server_updates")
    if server_updates:
        add(
            "server-updates",
            f"{server_updates} server {pluralize(server_updates, 'update')} available",
            "Updates may include schema, auth, or runtime fixes.",
            "info",
        )
    if budget_percent is not None and budget_percent >= 80:
        add(
            "budget",
            "Monthly budget pressure",
            f"Projected usage is at {budget_percent:.1f}% of the configured monthly budget.",
            "danger" if budget_percent >= 100 else "warning",
        )
    if int_row_value(control, "workspaces") == 0:
        add(
            "workspaces",
            "No workspaces configured",
            "Create a workspace before installing MCP servers or agents.",
            "info",
        )
    has_workspaces = int_row_value(control, "workspaces") > 0
    if int_row_value(control, "installed_servers") == 0 and has_workspaces:
        add(
            "installations",
            "No MCP servers installed",
            "The organization has workspaces but no connected tool servers yet.",
            "info",
        )
    return items[:8]


def format_duration_text(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value < 1000:
        return f"{value} ms"
    return f"{value / 1000:.1f} s"


def workspace_observability_health_score(
    *,
    usage: UsageSummaryResponse,
    runtime_attention: int,
    failed_agent_runs: int,
    tool_total: int,
    tool_failed: int,
    running_tool_calls: int,
    p95_tool_duration_ms: int | None,
    unattributed_tool_calls: int,
) -> int:
    completed_requests = usage.summary.succeeded + usage.summary.failed
    completed_tools = max(tool_total - running_tool_calls, 0)
    score = 100
    score -= min(24, failed_agent_runs * 8)
    score -= min(20, int(percent(usage.summary.failed, completed_requests) * 0.55))
    score -= min(20, int(percent(tool_failed, completed_tools) * 0.55))
    score -= min(15, runtime_attention * 5)
    if p95_tool_duration_ms is not None:
        if p95_tool_duration_ms >= 30_000:
            score -= 12
        elif p95_tool_duration_ms >= 10_000:
            score -= 7
        elif p95_tool_duration_ms >= 5_000:
            score -= 3
    if tool_total > 0:
        score -= min(8, int(percent(unattributed_tool_calls, tool_total) * 0.2))
    return max(min(score, 100), 0)


def workspace_observability_top_tool_row(row) -> WorkspaceObservabilityTopToolRow:
    calls = int_row_value(row, "calls")
    failed = int_row_value(row, "failed")
    server_name = str(row_value(row, "server_name", "") or "")
    tool_name = str(row_value(row, "tool_name", "") or "")
    return WorkspaceObservabilityTopToolRow(
        id=f"{server_name}:{tool_name}",
        serverName=server_name,
        toolName=tool_name,
        calls=calls,
        failed=failed,
        errorRate=percent(failed, calls),
        averageDurationMs=optional_duration(row_value(row, "average_duration_ms", None)),
        p95DurationMs=optional_duration(row_value(row, "p95_duration_ms", None)),
        lastCalledAt=row_value(row, "last_called_at", None),
    )


def workspace_observability_run_row(row) -> WorkspaceObservabilityAgentRunRow:
    input_tokens = int_row_value(row, "input_tokens")
    output_tokens = int_row_value(row, "output_tokens")
    return WorkspaceObservabilityAgentRunRow(
        id=row_value(row, "id"),
        agentId=row_value(row, "agent_id"),
        agentName=str(row_value(row, "agent_name", "") or "Unknown agent"),
        triggeredById=row_value(row, "triggered_by_id", None),
        triggeredByEmail=str(row_value(row, "triggered_by_email", "") or ""),
        triggeredByDisplayName=person_label(
            row_value(row, "first_name", None),
            row_value(row, "last_name", None),
            row_value(row, "triggered_by_email", None),
        ),
        triggerType=str(row_value(row, "trigger_type", "") or "chat"),
        status=str(row_value(row, "status", "") or "unknown"),
        requests=int_row_value(row, "requests"),
        failedRequests=int_row_value(row, "failed_requests"),
        inputTokens=input_tokens,
        outputTokens=output_tokens,
        totalTokens=input_tokens + output_tokens,
        costUsd=row_value(row, "cost_usd", Decimal("0")) or Decimal("0"),
        toolCalls=int_row_value(row, "tool_calls"),
        failedToolCalls=int_row_value(row, "failed_tool_calls"),
        traceId=str(row_value(row, "trace_id", "") or ""),
        spanId=str(row_value(row, "span_id", "") or ""),
        startedAt=row_value(row, "started_at"),
        finishedAt=row_value(row, "finished_at", None),
        error=str(row_value(row, "error", "") or ""),
    )


def workspace_observability_attention_items(
    *,
    usage: UsageSummaryResponse,
    summary: WorkspaceObservabilityDashboardSummary,
    recent_runs: list[WorkspaceObservabilityAgentRunRow],
    top_tools: list[WorkspaceObservabilityTopToolRow],
) -> list[WorkspaceObservabilityAttentionItem]:
    items: list[WorkspaceObservabilityAttentionItem] = []

    def add(key: str, label: str, detail: str, severity: str, href: str = "") -> None:
        items.append(
            WorkspaceObservabilityAttentionItem(
                key=key,
                label=label,
                detail=detail,
                severity=severity,
                href=href,
            )
        )

    for run in [run for run in recent_runs if run.status == "failed"][:3]:
        add(
            f"run-{run.id}",
            f"{run.agent_name} run failed",
            run.error or f"{run.requests} model calls, {run.tool_calls} tool calls.",
            "danger",
            href=f"agent-runs/{run.id}",
        )
    if usage.summary.failed:
        add(
            "llm-failures",
            f"{usage.summary.failed} failed model {pluralize(usage.summary.failed, 'request')}",
            "Review provider errors, model limits, and failing run traces.",
            "warning",
        )
    if summary.failed_tool_calls:
        failed_tool_label = pluralize(summary.failed_tool_calls, "call")
        add(
            "tool-failures",
            f"{summary.failed_tool_calls} failed MCP tool {failed_tool_label}",
            "Failures are grouped by tool below so schema, auth, and upstream errors "
            "are easier to isolate.",
            "warning",
        )
    slow_tools = [tool for tool in top_tools if (tool.p95_duration_ms or 0) >= 5_000]
    if slow_tools:
        tool = slow_tools[0]
        add(
            "slow-tools",
            f"{tool.tool_name} has slow p95 latency",
            f"p95 {format_duration_text(tool.p95_duration_ms)} on {tool.server_name}.",
            "warning",
        )
    if summary.runtime_sessions_needing_attention:
        runtime_label = pluralize(summary.runtime_sessions_needing_attention, "session")
        add(
            "runtime-sessions",
            f"{summary.runtime_sessions_needing_attention} runtime {runtime_label} need review",
            "Runtime failures can make installed MCP servers fail after selection.",
            "warning",
        )
    if summary.unattributed_tool_calls:
        unattributed_tool_label = pluralize(summary.unattributed_tool_calls, "call")
        add(
            "unattributed-tools",
            f"{summary.unattributed_tool_calls} unattributed tool {unattributed_tool_label}",
            "Missing user, agent, or run IDs make audit trails harder to follow.",
            "info",
        )
    if not items:
        add(
            "healthy",
            "No active observability issues",
            "Recent agent turns, model calls, and MCP tool calls are not showing triage signals.",
            "success",
        )
    severity_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(items, key=lambda item: severity_order.get(item.severity, 9))[:8]


def dashboard_workspace_row(row) -> OrganizationDashboardWorkspaceRow:
    return OrganizationDashboardWorkspaceRow(
        id=row_value(row, "id"),
        name=str(row_value(row, "name", "")),
        slug=str(row_value(row, "slug", "")),
        status=str(row_value(row, "status", "")),
        requests=int_row_value(row, "requests"),
        failedRequests=int_row_value(row, "failed_requests"),
        totalTokens=int_row_value(row, "total_tokens"),
        costUsd=decimal_row_value(row, "cost_usd"),
        toolCalls=int_row_value(row, "tool_calls"),
        failedToolCalls=int_row_value(row, "failed_tool_calls"),
        agents=int_row_value(row, "agents"),
        activeAgents=int_row_value(row, "active_agents"),
        installations=int_row_value(row, "installations"),
        enabledInstallations=int_row_value(row, "enabled_installations"),
        serversNeedingAttention=int_row_value(row, "servers_needing_attention"),
        serverUpdates=int_row_value(row, "server_updates"),
        toolCount=int_row_value(row, "tool_count"),
        runtimeSessions=int_row_value(row, "runtime_sessions"),
        activeRuntimeSessions=int_row_value(row, "active_runtime_sessions"),
        runtimeSessionsNeedingAttention=int_row_value(
            row,
            "runtime_sessions_needing_attention",
        ),
        latestActivityAt=row_value(row, "latest_activity_at", None),
    )


def dashboard_runtime_row(row) -> OrganizationDashboardRuntimeRow:
    runtime = str(row_value(row, "runtime", "") or "")
    return OrganizationDashboardRuntimeRow(
        runtime=runtime,
        label=runtime_label(runtime),
        total=int_row_value(row, "total"),
        enabled=int_row_value(row, "enabled"),
        attention=int_row_value(row, "attention"),
    )


def dashboard_provider_row(row) -> OrganizationDashboardProviderRow:
    return OrganizationDashboardProviderRow(
        provider=str(row_value(row, "provider", "") or ""),
        total=int_row_value(row, "total"),
        active=int_row_value(row, "active"),
        apiKey=int_row_value(row, "api_key"),
        oauth=int_row_value(row, "oauth"),
    )


def dashboard_tool_row(row) -> OrganizationDashboardToolRow:
    calls = int_row_value(row, "calls")
    failed = int_row_value(row, "failed")
    server_name = str(row_value(row, "server_name", "") or "")
    tool_name = str(row_value(row, "tool_name", "") or "")
    workspace_id = row_value(row, "workspace_id", None)
    return OrganizationDashboardToolRow(
        id=f"{workspace_id or 'organization'}:{server_name}:{tool_name}",
        serverName=server_name,
        toolName=tool_name,
        workspaceId=workspace_id,
        workspaceName=str(row_value(row, "workspace_name", "") or "Unknown workspace"),
        calls=calls,
        failed=failed,
        errorRate=percent(failed, calls),
        averageDurationMs=optional_duration(row_value(row, "average_duration_ms", None)),
        p95DurationMs=optional_duration(row_value(row, "p95_duration_ms", None)),
        lastCalledAt=row_value(row, "last_called_at", None),
    )


async def workspace_observability_dashboard(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    breakdown_limit: int = DASHBOARD_DEFAULT_LIMIT,
) -> WorkspaceObservabilityDashboardResponse:
    if not 1 <= breakdown_limit <= DASHBOARD_MAX_LIMIT:
        raise ValueError(f"breakdownLimit must be between 1 and {DASHBOARD_MAX_LIMIT}")

    usage = await workspace_usage_summary(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
        breakdown_limit=breakdown_limit,
    )
    window = resolve_usage_summary_window(start_date=start_date, end_date=end_date)
    control = await repository.workspace_observability_control_counts(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        started_at_from=window.started_at_from,
        started_at_to=window.started_at_to,
    )
    tool_totals = await repository.workspace_observability_tool_usage_totals(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        started_at_from=window.started_at_from,
        started_at_to=window.started_at_to,
    )
    llm_attribution = await repository.workspace_observability_llm_attribution_counts(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        started_at_from=window.started_at_from,
        started_at_to=window.started_at_to,
    )
    tool_rows = await repository.workspace_observability_top_tool_rows(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        started_at_from=window.started_at_from,
        started_at_to=window.started_at_to,
        limit=breakdown_limit,
    )
    run_rows = await repository.workspace_observability_recent_run_rows(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        started_at_from=window.started_at_from,
        started_at_to=window.started_at_to,
        limit=max(10, breakdown_limit),
    )
    top_tools = [workspace_observability_top_tool_row(row) for row in tool_rows]
    recent_runs = [workspace_observability_run_row(row) for row in run_rows]
    tool_total = int_row_value(tool_totals, "tool_calls")
    tool_failed = int_row_value(tool_totals, "failed_tool_calls")
    running_tools = int_row_value(tool_totals, "running_tool_calls")
    completed_tools = max(tool_total - running_tools, 0)
    attributed_tool_calls = int_row_value(tool_totals, "attributed_tool_calls")
    unattributed_tool_calls = int_row_value(tool_totals, "unattributed_tool_calls")
    p95_tool_duration_ms = optional_duration(row_value(tool_totals, "p95_tool_duration_ms", None))
    runtime_attention = int_row_value(control, "runtime_sessions_needing_attention")
    summary = WorkspaceObservabilityDashboardSummary(
        healthScore=workspace_observability_health_score(
            usage=usage,
            runtime_attention=runtime_attention,
            failed_agent_runs=int_row_value(control, "failed_agent_runs"),
            tool_total=tool_total,
            tool_failed=tool_failed,
            running_tool_calls=running_tools,
            p95_tool_duration_ms=p95_tool_duration_ms,
            unattributed_tool_calls=unattributed_tool_calls,
        ),
        agentRuns=int_row_value(control, "agent_runs"),
        failedAgentRuns=int_row_value(control, "failed_agent_runs"),
        runningAgentRuns=int_row_value(control, "running_agent_runs"),
        requests=usage.summary.requests,
        requestSuccessRate=success_rate(
            usage.summary.succeeded,
            usage.summary.succeeded + usage.summary.failed,
        ),
        failedRequests=usage.summary.failed,
        totalTokens=usage.summary.total_tokens,
        costUsd=usage.summary.cost_usd,
        toolCalls=tool_total,
        toolSuccessRate=success_rate(completed_tools - tool_failed, completed_tools),
        failedToolCalls=tool_failed,
        runningToolCalls=running_tools,
        averageToolDurationMs=optional_duration(
            row_value(tool_totals, "average_tool_duration_ms", None)
        ),
        p95ToolDurationMs=p95_tool_duration_ms,
        attributedToolCalls=attributed_tool_calls,
        unattributedToolCalls=unattributed_tool_calls,
        attributedLlmCalls=int_row_value(llm_attribution, "attributed_llm_calls"),
        unattributedLlmCalls=int_row_value(llm_attribution, "unattributed_llm_calls"),
        activeRuntimeSessions=int_row_value(control, "active_runtime_sessions"),
        runtimeSessionsNeedingAttention=runtime_attention,
    )
    return WorkspaceObservabilityDashboardResponse(
        window=usage.window,
        summary=summary,
        activity=usage.daily,
        attention=workspace_observability_attention_items(
            usage=usage,
            summary=summary,
            recent_runs=recent_runs,
            top_tools=top_tools,
        ),
        topTools=top_tools,
        topModels=usage.by_model[:breakdown_limit],
        topAgents=usage.by_agent[:breakdown_limit],
        topUsers=usage.by_user[:breakdown_limit],
        recentRuns=recent_runs,
    )


async def organization_dashboard(
    session: AsyncSession,
    *,
    organization_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    breakdown_limit: int = DASHBOARD_DEFAULT_LIMIT,
) -> OrganizationDashboardResponse:
    if not 1 <= breakdown_limit <= DASHBOARD_MAX_LIMIT:
        raise ValueError(f"breakdownLimit must be between 1 and {DASHBOARD_MAX_LIMIT}")

    usage = await organization_usage_summary(
        session,
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        breakdown_limit=breakdown_limit,
    )
    window = resolve_usage_summary_window(start_date=start_date, end_date=end_date)
    catalog_stale_before = datetime.now(UTC) - DASHBOARD_CATALOG_STALE_AFTER
    control, tool_totals, workspace_rows, runtime_rows, provider_rows, tool_rows = (
        await repository.organization_dashboard_control_counts(
            session,
            organization_id=organization_id,
            catalog_stale_before=catalog_stale_before,
        ),
        await repository.organization_dashboard_tool_usage_totals(
            session,
            organization_id=organization_id,
            started_at_from=window.started_at_from,
            started_at_to=window.started_at_to,
        ),
        await repository.organization_dashboard_workspace_rows(
            session,
            organization_id=organization_id,
            started_at_from=window.started_at_from,
            started_at_to=window.started_at_to,
            limit=breakdown_limit,
        ),
        await repository.organization_dashboard_runtime_rows(
            session,
            organization_id=organization_id,
        ),
        await repository.organization_dashboard_provider_rows(
            session,
            organization_id=organization_id,
        ),
        await repository.organization_dashboard_top_tool_rows(
            session,
            organization_id=organization_id,
            started_at_from=window.started_at_from,
            started_at_to=window.started_at_to,
            limit=breakdown_limit,
        ),
    )

    cost = usage.summary.cost_usd
    projected_cost = projected_monthly_cost(cost, usage.window)
    monthly_budget = decimal_row_value(control, "monthly_budget_usd")
    if monthly_budget <= 0:
        monthly_budget = None
    budget_percent = budget_utilization_percent(
        projected_cost=projected_cost,
        monthly_budget=monthly_budget,
    )
    tool_total = int_row_value(tool_totals, "tool_calls")
    tool_failed = int_row_value(tool_totals, "failed_tool_calls")
    tool_running = int_row_value(tool_totals, "running_tool_calls")
    completed_requests = usage.summary.succeeded + usage.summary.failed
    tool_success_total = max(tool_total - tool_running, 0)
    health_score = dashboard_health_score(
        control=control,
        usage=usage,
        tool_failed=tool_failed,
        tool_total=tool_success_total,
        budget_percent=budget_percent,
    )

    return OrganizationDashboardResponse(
        window=usage.window,
        summary=OrganizationDashboardSummary(
            healthScore=health_score,
            workspaces=int_row_value(control, "workspaces"),
            activeWorkspaces=int_row_value(control, "active_workspaces"),
            members=int_row_value(control, "members"),
            activeMembers=int_row_value(control, "active_members"),
            requests=usage.summary.requests,
            requestSuccessRate=success_rate(usage.summary.succeeded, completed_requests),
            failedRequests=usage.summary.failed,
            totalTokens=usage.summary.total_tokens,
            costUsd=cost,
            projectedMonthlyCostUsd=projected_cost,
            toolCalls=usage.summary.tool_calls,
            toolSuccessRate=success_rate(tool_success_total - tool_failed, tool_success_total),
            averageToolDurationMs=optional_duration(
                row_value(tool_totals, "average_tool_duration_ms", None)
            ),
            agents=int_row_value(control, "agents"),
            activeAgents=int_row_value(control, "active_agents"),
            tools=int_row_value(control, "tools"),
            installedServers=int_row_value(control, "installed_servers"),
            enabledServers=int_row_value(control, "enabled_servers"),
            serversNeedingAttention=int_row_value(control, "servers_needing_attention"),
            serverUpdates=int_row_value(control, "server_updates"),
            runtimeSessions=int_row_value(control, "runtime_sessions"),
            activeRuntimeSessions=int_row_value(control, "active_runtime_sessions"),
            runtimeSessionsNeedingAttention=int_row_value(
                control,
                "runtime_sessions_needing_attention",
            ),
            catalogSources=int_row_value(control, "catalog_sources"),
            enabledCatalogSources=int_row_value(control, "enabled_catalog_sources"),
            catalogErrors=int_row_value(control, "catalog_errors"),
            staleCatalogSources=int_row_value(control, "stale_catalog_sources"),
            providerCredentials=int_row_value(control, "provider_credentials"),
            activeProviderCredentials=int_row_value(control, "active_provider_credentials"),
            resourceLimits=int_row_value(control, "resource_limits"),
            usageBudgets=int_row_value(control, "usage_budgets"),
            monthlyBudgetUsd=monthly_budget,
            budgetUtilizationPercent=budget_percent,
        ),
        daily=usage.daily,
        workspaces=[dashboard_workspace_row(row) for row in workspace_rows],
        topModels=usage.by_model[:breakdown_limit],
        topAgents=usage.by_agent[:breakdown_limit],
        topTools=[dashboard_tool_row(row) for row in tool_rows],
        runtimeMix=[dashboard_runtime_row(row) for row in runtime_rows],
        catalog=OrganizationDashboardCatalogHealth(
            total=int_row_value(control, "catalog_sources"),
            enabled=int_row_value(control, "enabled_catalog_sources"),
            synced=int_row_value(control, "synced_catalog_sources"),
            errors=int_row_value(control, "catalog_errors"),
            stale=int_row_value(control, "stale_catalog_sources"),
        ),
        providers=[dashboard_provider_row(row) for row in provider_rows],
        attention=dashboard_attention_items(
            control=control,
            usage=usage,
            tool_failed=tool_failed,
            budget_percent=budget_percent,
        ),
    )


def usage_breakdown_identity(row, group_key: str) -> tuple[str, str]:
    if group_key == "user":
        return (
            bucket_id(row_value(row, "user_id", None), "unattributed"),
            person_label(
                row_value(row, "first_name", None),
                row_value(row, "last_name", None),
                row_value(row, "email", None),
            ),
        )
    if group_key == "workspace":
        return (
            bucket_id(row_value(row, "workspace_id", None), "unknown-workspace"),
            display_label(
                name=row_value(row, "workspace_name", None),
                fallback="Unknown workspace",
            ),
        )
    if group_key == "agent":
        return (
            bucket_id(row_value(row, "agent_id", None), "unattributed-agent"),
            display_label(
                name=row_value(row, "agent_name", None),
                fallback="Unattributed agent",
            ),
        )
    provider = str(row_value(row, "provider", ""))
    model = str(row_value(row, "model", ""))
    return f"{provider}:{model}", f"{provider} / {model}"


async def usage_summary_response(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    breakdown_limit: int = USAGE_SUMMARY_DEFAULT_BREAKDOWN_LIMIT,
) -> UsageSummaryResponse:
    if not 1 <= breakdown_limit <= USAGE_SUMMARY_MAX_BREAKDOWN_LIMIT:
        raise ValueError(
            f"breakdownLimit must be between 1 and {USAGE_SUMMARY_MAX_BREAKDOWN_LIMIT}"
        )
    window = resolve_usage_summary_window(start_date=start_date, end_date=end_date)
    query_limit = USAGE_SUMMARY_MAX_BREAKDOWN_LIMIT
    scope = {
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "started_at_from": window.started_at_from,
        "started_at_to": window.started_at_to,
        "breakdown_limit": query_limit,
    }
    llm_rows = await repository.llm_usage_summary_rows(session, **scope)
    tool_rows = await repository.mcp_tool_usage_summary_rows(session, **scope)

    totals_row: Any = {}
    total_tool_calls = 0
    breakdowns: dict[str, dict[str, dict[str, Any]]] = {
        "user": {},
        "workspace": {},
        "agent": {},
        "model": {},
    }
    daily: dict[date, dict[str, Any]] = {}

    for row in llm_rows:
        group_key = str(row_value(row, "group_key", ""))
        if group_key == "total":
            totals_row = row
        elif group_key == "day":
            add_llm_daily(daily, row=row)
        elif group_key in breakdowns:
            key, label = usage_breakdown_identity(row, group_key)
            add_llm_breakdown(breakdowns[group_key], key=key, label=label, row=row)

    for row in tool_rows:
        group_key = str(row_value(row, "group_key", ""))
        if group_key == "total":
            total_tool_calls = int(row_value(row, "tool_calls"))
        elif group_key == "day":
            add_tool_daily(
                daily,
                point_date=usage_date(row_value(row, "usage_day")),
                tool_calls=int(row_value(row, "tool_calls")),
            )
        elif group_key in ("user", "workspace", "agent"):
            key, label = usage_breakdown_identity(row, group_key)
            add_tool_breakdown(
                breakdowns[group_key],
                key=key,
                label=label,
                tool_calls=int(row_value(row, "tool_calls")),
            )

    return UsageSummaryResponse(
        window=UsageSummaryWindow(
            startDate=window.start_date,
            endDate=window.end_date,
            timezone="UTC",
            breakdownLimit=breakdown_limit,
        ),
        summary=usage_totals_response(totals_row, tool_calls=total_tool_calls),
        byUser=breakdown_rows(breakdowns["user"], limit=breakdown_limit),
        byWorkspace=breakdown_rows(breakdowns["workspace"], limit=breakdown_limit),
        byAgent=breakdown_rows(breakdowns["agent"], limit=breakdown_limit),
        byModel=breakdown_rows(breakdowns["model"], limit=breakdown_limit),
        daily=trend_points(daily),
    )


async def organization_usage_summary(
    session: AsyncSession,
    *,
    organization_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    breakdown_limit: int = USAGE_SUMMARY_DEFAULT_BREAKDOWN_LIMIT,
) -> UsageSummaryResponse:
    return await usage_summary_response(
        session,
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        breakdown_limit=breakdown_limit,
    )


async def workspace_usage_summary(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    breakdown_limit: int = USAGE_SUMMARY_DEFAULT_BREAKDOWN_LIMIT,
) -> UsageSummaryResponse:
    return await usage_summary_response(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
        breakdown_limit=breakdown_limit,
    )


async def user_usage_summary(
    session: AsyncSession,
    *,
    user_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    breakdown_limit: int = USAGE_SUMMARY_DEFAULT_BREAKDOWN_LIMIT,
) -> UsageSummaryResponse:
    return await usage_summary_response(
        session,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        breakdown_limit=breakdown_limit,
    )


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


async def agent_run_usage_summaries(
    session: AsyncSession,
    *,
    agent_run_ids: list[UUID],
) -> dict[UUID, UsageSummaryTotals]:
    if not agent_run_ids:
        return {}
    llm_rows = await repository.llm_usage_totals_by_agent_run(
        session,
        agent_run_ids=agent_run_ids,
    )
    tool_rows = await repository.mcp_tool_call_counts_by_agent_run(
        session,
        agent_run_ids=agent_run_ids,
    )
    llm_by_run = {
        row_value(row, "agent_run_id"): row
        for row in llm_rows
        if row_value(row, "agent_run_id") is not None
    }
    tool_calls_by_run = {
        row_value(row, "agent_run_id"): int(row_value(row, "tool_calls", 0))
        for row in tool_rows
        if row_value(row, "agent_run_id") is not None
    }
    empty_totals = {
        "requests": 0,
        "succeeded": 0,
        "failed": 0,
        "running": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": Decimal("0"),
    }
    return {
        agent_run_id: usage_totals_response(
            llm_by_run.get(agent_run_id, empty_totals),
            tool_calls=tool_calls_by_run.get(agent_run_id, 0),
        )
        for agent_run_id in agent_run_ids
    }


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
