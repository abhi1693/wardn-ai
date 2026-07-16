import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.limits import repository
from app.modules.limits.models import ResourceLimit, UsageBudget


class ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


class RecordingSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.statement = None

    async def execute(self, statement) -> ScalarResult:
        self.statement = statement
        return ScalarResult(self.result)


def compiled_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_resource_limit_upsert_uses_constraint_conflict_update() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    limit = ResourceLimit(
        id=uuid.uuid4(),
        scope_type="organization",
        scope_id=uuid.uuid4(),
        limit_key="agents.per_organization",
        value=10,
        created_at=now,
        updated_at=now,
    )
    session = RecordingSession(limit)

    result = await repository.upsert_resource_limit(
        session,
        scope_type=limit.scope_type,
        scope_id=limit.scope_id,
        limit_key=limit.limit_key,
        value=limit.value,
    )

    assert result is limit
    assert "ON CONFLICT ON CONSTRAINT uq_resource_limits_scope_key DO UPDATE" in compiled_sql(
        session.statement
    )
    assert "RETURNING resource_limits" in compiled_sql(session.statement)


@pytest.mark.asyncio
async def test_usage_budget_upsert_uses_constraint_conflict_update() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    budget = UsageBudget(
        id=uuid.uuid4(),
        scope_type="workspace",
        scope_id=uuid.uuid4(),
        budget_key="llm.cost_usd.per_month",
        value=Decimal("25"),
        unit="cost_usd",
        period="month",
        period_anchor=None,
        model_filter="gpt-5",
        created_at=now,
        updated_at=now,
    )
    session = RecordingSession(budget)

    result = await repository.upsert_usage_budget(
        session,
        scope_type=budget.scope_type,
        scope_id=budget.scope_id,
        budget_key=budget.budget_key,
        value=budget.value,
        unit=budget.unit,
        period=budget.period,
        period_anchor=budget.period_anchor,
        model_filter=budget.model_filter,
    )

    assert result is budget
    assert (
        "ON CONFLICT ON CONSTRAINT uq_usage_budgets_scope_key_model DO UPDATE"
        in compiled_sql(session.statement)
    )
    assert "RETURNING usage_budgets" in compiled_sql(session.statement)
