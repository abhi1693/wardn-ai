import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.limits import service
from app.modules.limits.exceptions import InvalidLimitKeyError, LimitExceededError
from app.modules.limits.models import UsageBudget


class FakeSession:
    execute = None


def usage_budget(
    *,
    scope_type: str = "user",
    scope_id: uuid.UUID | None = None,
    budget_key: str = "llm.cost_usd.per_month",
    value: Decimal = Decimal("10"),
    unit: str = "cost_usd",
    period: str = "month",
    model_filter: str = "",
) -> UsageBudget:
    return UsageBudget(
        id=uuid.uuid4(),
        scope_type=scope_type,
        scope_id=scope_id or uuid.uuid4(),
        budget_key=budget_key,
        value=value,
        unit=unit,
        period=period,
        model_filter=model_filter,
        created_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
    )


def test_usage_budget_window_defaults_to_calendar_month() -> None:
    start, end = service.usage_budget_window(
        period="month",
        now=datetime(2026, 7, 9, 12, 30, tzinfo=UTC),
    )

    assert start == datetime(2026, 7, 1, tzinfo=UTC)
    assert end == datetime(2026, 8, 1, tzinfo=UTC)


def test_usage_budget_unit_period_matches_key() -> None:
    assert service.usage_budget_unit_period("llm.tokens.per_day", None, None) == (
        "tokens",
        "day",
    )

    with pytest.raises(InvalidLimitKeyError):
        service.usage_budget_unit_period("llm.tokens.per_day", "cost_usd", "day")


@pytest.mark.asyncio
async def test_require_llm_budget_available_rejects_exhausted_budget(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    budget = usage_budget(
        scope_type="user",
        scope_id=user_id,
        value=Decimal("5"),
        model_filter="gpt-4.1-mini",
    )

    async def list_usage_budgets_for_scopes(session, *, scope_chain, model):
        assert ("organization", organization_id) in scope_chain
        assert ("workspace", workspace_id) in scope_chain
        assert ("user", user_id) in scope_chain
        assert ("agent", agent_id) in scope_chain
        assert model == "gpt-4.1-mini"
        return [budget]

    async def llm_usage_budget_spend(session, *, budget, window_start, window_end):
        return Decimal("5")

    monkeypatch.setattr(
        service.repository,
        "list_usage_budgets_for_scopes",
        list_usage_budgets_for_scopes,
    )
    monkeypatch.setattr(service.repository, "llm_usage_budget_spend", llm_usage_budget_spend)

    with pytest.raises(LimitExceededError):
        await service.require_llm_budget_available(
            FakeSession(),
            service.LLMBudgetContext(
                organization_id=organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                agent_id=agent_id,
                model="gpt-4.1-mini",
                now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
            ),
        )


@pytest.mark.asyncio
async def test_require_llm_budget_available_allows_remaining_budget(monkeypatch) -> None:
    budget = usage_budget(value=Decimal("5"))

    async def list_usage_budgets_for_scopes(session, *, scope_chain, model):
        return [budget]

    async def llm_usage_budget_spend(session, *, budget, window_start, window_end):
        return Decimal("4.999")

    monkeypatch.setattr(
        service.repository,
        "list_usage_budgets_for_scopes",
        list_usage_budgets_for_scopes,
    )
    monkeypatch.setattr(service.repository, "llm_usage_budget_spend", llm_usage_budget_spend)

    await service.require_llm_budget_available(
        FakeSession(),
        service.LLMBudgetContext(
            organization_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            user_id=None,
            agent_id=None,
            model="gpt-4.1-mini",
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        ),
    )
