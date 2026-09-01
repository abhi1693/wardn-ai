import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.limits import service
from app.modules.limits.exceptions import InvalidLimitKeyError, LimitExceededError
from app.modules.limits.models import ResourceLimit, UsageBudget


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement) -> None:
        self.statements.append(statement)


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


def resource_limit(
    *,
    scope_type: str = "workspace",
    scope_id: uuid.UUID | None = None,
    limit_key: str = service.AGENT_CHAT_MAX_TOOL_ROUNDS_PER_RUN,
    value: int = 100,
) -> ResourceLimit:
    return ResourceLimit(
        id=uuid.uuid4(),
        scope_type=scope_type,
        scope_id=scope_id or uuid.uuid4(),
        limit_key=limit_key,
        value=value,
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


def test_quota_lock_id_is_stable_and_scope_specific() -> None:
    organization_id = uuid.uuid4()
    first = service.quota_scope(service.AGENTS_PER_ORGANIZATION, organization_id)
    same = service.quota_scope(service.AGENTS_PER_ORGANIZATION, organization_id)
    different = service.quota_scope(service.WORKSPACES_PER_ORGANIZATION, organization_id)

    assert service.quota_lock_id(first) == service.quota_lock_id(same)
    assert service.quota_lock_id(first) != service.quota_lock_id(different)


@pytest.mark.parametrize(
    "limit_key",
    [
        service.MCP_RUNTIME_PUBLIC_EGRESS_PER_WORKSPACE,
        service.MCP_RUNTIME_PRIVATE_EGRESS_PER_WORKSPACE,
        service.MCP_RUNTIME_KUBERNETES_API_EGRESS_PER_WORKSPACE,
        service.MCP_RUNTIME_NETWORK_ISOLATION_DISABLE_PER_WORKSPACE,
        service.MCP_RUNTIME_CUSTOM_EGRESS_RULES_PER_INSTALLATION,
    ],
)
def test_runtime_policy_limit_keys_are_supported(limit_key: str) -> None:
    assert service.normalize_limit_key(limit_key) == limit_key


def test_agent_chat_tool_round_limit_key_is_supported() -> None:
    assert (
        service.normalize_limit_key(service.AGENT_CHAT_MAX_TOOL_ROUNDS_PER_RUN)
        == service.AGENT_CHAT_MAX_TOOL_ROUNDS_PER_RUN
    )


@pytest.mark.asyncio
async def test_effective_agent_chat_max_tool_rounds_uses_workspace_limit(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    workspace_limit = resource_limit(scope_id=workspace_id, value=42)

    async def get_limit(session, *, scope_type, scope_id, limit_key):
        if scope_type == "workspace":
            assert scope_id == workspace_id
            assert limit_key == service.AGENT_CHAT_MAX_TOOL_ROUNDS_PER_RUN
            return workspace_limit
        raise AssertionError("workspace limit should be evaluated first")

    monkeypatch.setattr(service.repository, "get_limit", get_limit)

    async def current_entitlements(session):
        return uuid.uuid4(), type(
            "Entitlements",
            (),
            {"limits": {service.AGENT_CHAT_MAX_TOOL_ROUNDS_PER_RUN: 100}},
        )()

    monkeypatch.setattr(service, "current_entitlements", current_entitlements)

    assert await service.effective_agent_chat_max_tool_rounds(
        RecordingSession(),
        organization_id=organization_id,
        workspace_id=workspace_id,
    ) == 42


@pytest.mark.asyncio
async def test_license_ceiling_cannot_be_raised_by_database(monkeypatch) -> None:
    configured = resource_limit(limit_key=service.AGENTS_PER_ORGANIZATION, value=999)

    async def effective_limit(*args, **kwargs):
        return configured

    async def current_entitlements(session):
        return uuid.uuid4(), type(
            "Entitlements",
            (),
            {"limits": {service.AGENTS_PER_ORGANIZATION: 10}},
        )()

    monkeypatch.setattr(service, "effective_limit", effective_limit)
    monkeypatch.setattr(service, "current_entitlements", current_entitlements)

    with pytest.raises(LimitExceededError, match="10/10"):
        await service.require_limit_available(
            RecordingSession(),
            limit_key=service.AGENTS_PER_ORGANIZATION,
            scope_chain=[("organization", uuid.uuid4())],
            current_count=10,
        )


@pytest.mark.asyncio
async def test_lock_quota_capacity_acquires_unique_locks_in_sorted_order() -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    scopes = [
        service.quota_scope(service.AGENTS_PER_WORKSPACE, workspace_id),
        service.quota_scope(service.AGENTS_PER_ORGANIZATION, organization_id),
        service.quota_scope(service.AGENTS_PER_WORKSPACE, workspace_id),
    ]
    session = RecordingSession()

    await service.lock_quota_capacity(session, scopes)

    lock_ids = [next(iter(statement.compile().params.values())) for statement in session.statements]
    assert lock_ids == sorted({service.quota_lock_id(scope) for scope in scopes})
    assert all("pg_advisory_xact_lock" in str(statement) for statement in session.statements)


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
            RecordingSession(),
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
        RecordingSession(),
        service.LLMBudgetContext(
            organization_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            user_id=None,
            agent_id=None,
            model="gpt-4.1-mini",
            now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        ),
    )
