import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability import repository, service
from app.modules.observability.models import LLMModelPrice, LLMTrace, LLMUsageRecord
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True


class FakeRow(tuple):
    def __new__(cls, values, mapping):
        row = tuple.__new__(cls, values)
        row._mapping = mapping
        return row


def usage_row(*values, requests=0, input_tokens=0, output_tokens=0, cost_usd="0"):
    return FakeRow(
        values,
        {
            "requests": requests,
            "succeeded": requests,
            "failed": 0,
            "running": 0,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": Decimal(cost_usd),
        },
    )


def test_calculate_llm_cost_uses_cache_prices() -> None:
    price = LLMModelPrice(
        provider="openai_api_key",
        model="gpt-4o-mini",
        input_usd_per_1m_tokens=Decimal("0.1500000000"),
        output_usd_per_1m_tokens=Decimal("0.6000000000"),
        cache_read_usd_per_1m_tokens=Decimal("0.0750000000"),
        cache_write_usd_per_1m_tokens=Decimal("0.3000000000"),
    )
    usage = service.LLMTokenUsage(
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_read_input_tokens=100_000,
        cache_write_input_tokens=200_000,
    )

    cost = service.calculate_llm_cost(price, usage)

    assert cost == Decimal("0.4725000000")


def test_openrouter_prefill_response_converts_per_token_prices() -> None:
    response = service.openrouter_prefill_response(
        provider="openai",
        model="gpt-4.1-mini",
        entry={
            "id": "openai/gpt-4.1-mini",
            "name": "OpenAI: GPT-4.1 Mini",
            "pricing": {
                "prompt": "0.0000004",
                "completion": "0.0000016",
                "input_cache_read": "0.0000001",
                "input_cache_write": "0.0000005",
            },
        },
    )

    assert response.found is True
    assert response.input_usd_per_1m_tokens == Decimal("0.4000000000")
    assert response.output_usd_per_1m_tokens == Decimal("1.6000000000")
    assert response.cache_read_usd_per_1m_tokens == Decimal("0.1000000000")
    assert response.cache_write_usd_per_1m_tokens == Decimal("0.5000000000")
    assert response.source == "openrouter"
    assert response.source_model_id == "openai/gpt-4.1-mini"


def test_openrouter_matching_maps_openai_chatgpt_to_openai_slug() -> None:
    assert service.openrouter_entry_matches_model(
        {"id": "openai/gpt-4.1-mini"},
        provider="openai_chatgpt",
        model="gpt-4.1-mini",
    )


@pytest.mark.asyncio
async def test_record_llm_usage_creates_trace_and_usage_record(monkeypatch) -> None:
    async def get_model_price(*args, **kwargs):
        return LLMModelPrice(
            provider="openai_api_key",
            model="gpt-4o-mini",
            input_usd_per_1m_tokens=Decimal("0.1500000000"),
            output_usd_per_1m_tokens=Decimal("0.6000000000"),
        )

    monkeypatch.setattr(service.repository, "get_model_price", get_model_price)
    session = FakeSession()
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    record = await service.record_llm_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
        provider="openai_api_key",
        model="gpt-4o-mini",
        usage=service.LLMTokenUsage(
            input_tokens=1_000,
            output_tokens=500,
            total_tokens=1_500,
        ),
        started_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 9, 12, 0, 1, tzinfo=UTC),
        status="succeeded",
    )

    assert record.organization_id == organization_id
    assert record.workspace_id == workspace_id
    assert record.cost_usd == Decimal("0.0004500000")
    assert any(isinstance(item, LLMTrace) for item in session.added)
    assert any(isinstance(item, LLMUsageRecord) for item in session.added)
    assert session.flushed is True


def tool_invocation(
    *,
    status: str = "succeeded",
    is_error: bool = False,
    user_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    duration_ms: int | None = 120,
) -> MCPToolInvocation:
    return MCPToolInvocation(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        runtime_session_id=uuid.uuid4(),
        user_id=user_id,
        agent_id=agent_id,
        agent_run_id=agent_run_id,
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        tool_name="get_forecast",
        status=status,
        started_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 9, 12, 0, 1, tzinfo=UTC),
        duration_ms=duration_ms,
        input_size_bytes=42,
        output_size_bytes=84,
        is_error=is_error,
        error="",
    )


def test_tool_usage_read_includes_person_and_agent_labels() -> None:
    user_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    invocation = tool_invocation(user_id=user_id, agent_id=agent_id)
    user = User(
        id=user_id,
        email="user@example.com",
        first_name="Asha",
        last_name="Rao",
    )
    agent = Agent(
        id=agent_id,
        organization_id=invocation.organization_id,
        workspace_id=invocation.workspace_id,
        name="Workspace Assistant",
        instructions="Use tools.",
        scope="workspace",
        model_name="gpt-4o-mini",
    )

    response = service.tool_usage_read(invocation, user, agent)

    assert response.user_display_name == "Asha Rao"
    assert response.user_email == "user@example.com"
    assert response.agent_name == "Workspace Assistant"
    assert response.input_size_bytes == 42
    assert response.output_size_bytes == 84


def test_tool_usage_summary_counts_status_and_attribution() -> None:
    attributed = tool_invocation(
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
        duration_ms=100,
    )
    failed = tool_invocation(status="failed", is_error=True, duration_ms=300)
    running = tool_invocation(status="running", duration_ms=None)

    summary = service.tool_usage_summary([attributed, failed, running])

    assert summary.total == 3
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.running == 1
    assert summary.attributed == 1
    assert summary.unattributed == 2
    assert summary.average_duration_ms == 200


@pytest.mark.asyncio
async def test_list_workspace_mcp_tool_usage_uses_repository(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    invocation = tool_invocation(user_id=user_id)
    user = User(id=user_id, email="user@example.com")

    async def list_mcp_tool_usage(session, *, organization_id, workspace_id, limit):
        return [(invocation, user, None)]

    monkeypatch.setattr(service.repository, "list_mcp_tool_usage", list_mcp_tool_usage)

    response = await service.list_workspace_mcp_tool_usage(
        object(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=25,
    )

    assert response.summary.total == 1
    assert response.tool_calls[0].user_email == "user@example.com"


@pytest.mark.asyncio
async def test_usage_summary_merges_llm_and_tool_breakdowns(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    calls = []
    aggregate = {
        "requests": 2,
        "succeeded": 2,
        "failed": 0,
        "running": 0,
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": Decimal("0.000125"),
    }

    async def llm_usage_summary_rows(*args, **kwargs):
        calls.append(("llm", kwargs))
        return [
            {"group_key": "total", **aggregate},
            {
                "group_key": "user",
                "user_id": user_id,
                "first_name": "Asha",
                "last_name": "Rao",
                "email": "asha@example.com",
                **aggregate,
            },
            {
                "group_key": "workspace",
                "workspace_id": workspace_id,
                "workspace_name": "Default Workspace",
                **aggregate,
            },
            {
                "group_key": "agent",
                "agent_id": agent_id,
                "agent_name": "Workspace Assistant",
                **aggregate,
            },
            {
                "group_key": "model",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                **aggregate,
            },
            {"group_key": "day", "usage_day": date(2026, 7, 9), **aggregate},
        ]

    async def mcp_tool_usage_summary_rows(*args, **kwargs):
        calls.append(("mcp", kwargs))
        return [
            {"group_key": "total", "tool_calls": 3},
            {
                "group_key": "user",
                "user_id": user_id,
                "first_name": "Asha",
                "last_name": "Rao",
                "email": "asha@example.com",
                "tool_calls": 3,
            },
            {
                "group_key": "workspace",
                "workspace_id": workspace_id,
                "workspace_name": "Default Workspace",
                "tool_calls": 3,
            },
            {
                "group_key": "agent",
                "agent_id": agent_id,
                "agent_name": "Workspace Assistant",
                "tool_calls": 3,
            },
            {"group_key": "day", "usage_day": date(2026, 7, 9), "tool_calls": 3},
        ]

    monkeypatch.setattr(
        service.repository,
        "llm_usage_summary_rows",
        llm_usage_summary_rows,
    )
    monkeypatch.setattr(
        service.repository,
        "mcp_tool_usage_summary_rows",
        mcp_tool_usage_summary_rows,
    )

    response = await service.organization_usage_summary(
        object(),
        organization_id=organization_id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 10),
        breakdown_limit=10,
    )

    assert [name for name, _kwargs in calls] == ["llm", "mcp"]
    for _name, kwargs in calls:
        assert kwargs["organization_id"] == organization_id
        assert kwargs["started_at_from"] == datetime(2026, 7, 1, tzinfo=UTC)
        assert kwargs["started_at_to"] == datetime(2026, 7, 11, tzinfo=UTC)
        assert kwargs["breakdown_limit"] == 100
    assert response.window.start_date == date(2026, 7, 1)
    assert response.window.end_date == date(2026, 7, 10)
    assert response.window.breakdown_limit == 10
    assert response.summary.requests == 2
    assert response.summary.tool_calls == 3
    assert response.by_user[0].label == "Asha Rao"
    assert response.by_user[0].cost_usd == Decimal("0.000125")
    assert response.by_user[0].tool_calls == 3
    assert response.by_model[0].label == "openai / gpt-4.1-mini"
    assert response.daily[0].date == date(2026, 7, 9)
    assert response.daily[0].total_tokens == 150
    assert response.daily[0].tool_calls == 3


def test_usage_summary_window_defaults_to_thirty_days() -> None:
    window = service.resolve_usage_summary_window(today=date(2026, 7, 16))

    assert window.start_date == date(2026, 6, 17)
    assert window.end_date == date(2026, 7, 16)
    assert window.started_at_from == datetime(2026, 6, 17, tzinfo=UTC)
    assert window.started_at_to == datetime(2026, 7, 17, tzinfo=UTC)


def test_usage_breakdown_rows_enforces_requested_limit() -> None:
    buckets = {
        str(index): {
            "id": str(index),
            "label": f"User {index}",
            "requests": index,
            "inputTokens": 0,
            "outputTokens": 0,
            "costUsd": Decimal(index),
            "toolCalls": 0,
        }
        for index in range(5)
    }

    rows = service.breakdown_rows(buckets, limit=2)

    assert [row.id for row in rows] == ["4", "3"]


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (date(2026, 7, 17), date(2026, 7, 16), "on or before"),
        (date(2025, 7, 15), date(2026, 7, 16), "cannot exceed 366 days"),
    ],
)
def test_usage_summary_window_rejects_invalid_ranges(start_date, end_date, message) -> None:
    with pytest.raises(ValueError, match=message):
        service.resolve_usage_summary_window(start_date=start_date, end_date=end_date)


class EmptyMappingResult:
    def mappings(self):
        return self

    def all(self):
        return []


class CapturingQuerySession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return EmptyMappingResult()


@pytest.mark.asyncio
async def test_usage_summary_repository_uses_two_bounded_grouping_queries() -> None:
    session = CapturingQuerySession()
    scope = {
        "organization_id": uuid.uuid4(),
        "started_at_from": datetime(2026, 7, 1, tzinfo=UTC),
        "started_at_to": datetime(2026, 7, 11, tzinfo=UTC),
        "breakdown_limit": 25,
    }

    await repository.llm_usage_summary_rows(session, **scope)
    await repository.mcp_tool_usage_summary_rows(session, **scope)

    assert len(session.statements) == 2
    for statement in session.statements:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).upper()
        assert "GROUPING SETS" in sql
        assert "ROW_NUMBER() OVER" in sql
        assert "STARTED_AT >=" in sql
        assert "STARTED_AT <" in sql
        assert "TIMEZONE('UTC'" in sql
