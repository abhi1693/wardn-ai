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
async def test_fetch_openrouter_model_entries_follows_next_link(monkeypatch) -> None:
    calls: list[str] = []
    next_url = "https://openrouter.ai/api/v1/models?offset=500&limit=500"
    pages = {
        service.OPENROUTER_MODELS_URL: {
            "data": [{"id": "openai/gpt-4.1"}],
            "links": {"next": "/api/v1/models?offset=500&limit=500"},
        },
        next_url: {
            "data": [{"id": "openai/gpt-4.1-mini"}],
            "links": {"next": None},
        },
    }

    class FakeOpenRouterResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str):
            calls.append(url)
            return FakeOpenRouterResponse(pages[url])

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)

    entries = await service.fetch_openrouter_model_entries()

    assert calls == [service.OPENROUTER_MODELS_URL, next_url]
    assert [entry["id"] for entry in entries] == ["openai/gpt-4.1", "openai/gpt-4.1-mini"]


@pytest.mark.asyncio
async def test_create_missing_openrouter_model_prices_adds_matching_missing_prices(
    monkeypatch,
) -> None:
    existing_price = LLMModelPrice(
        provider="openai",
        model="gpt-4o-mini",
        input_usd_per_1m_tokens=Decimal("0.1500000000"),
        output_usd_per_1m_tokens=Decimal("0.6000000000"),
    )

    async def list_model_prices_for_provider_models(session, *, provider, models):
        assert provider == "openai"
        assert models == ["gpt-4.1-mini", "gpt-4o-mini", "missing-model"]
        return [existing_price]

    async def fetch_openrouter_model_entries():
        return [
            {
                "id": "openai/gpt-4.1-mini",
                "name": "OpenAI: GPT-4.1 Mini",
                "pricing": {
                    "prompt": "0.0000004",
                    "completion": "0.0000016",
                    "input_cache_read": "0.0000001",
                },
            },
            {
                "id": "openai/gpt-4o-mini",
                "name": "OpenAI: GPT-4o Mini",
                "pricing": {
                    "prompt": "0.00000015",
                    "completion": "0.0000006",
                },
            },
        ]

    monkeypatch.setattr(
        service.repository,
        "list_model_prices_for_provider_models",
        list_model_prices_for_provider_models,
    )
    monkeypatch.setattr(service, "fetch_openrouter_model_entries", fetch_openrouter_model_entries)

    session = FakeSession()
    created_count = await service.create_missing_openrouter_model_prices(
        session,
        provider=" OpenAI ",
        models=["gpt-4.1-mini", "gpt-4o-mini", "missing-model", "gpt-4.1-mini"],
    )

    assert created_count == 1
    assert session.flushed is True
    [created_price] = session.added
    assert isinstance(created_price, LLMModelPrice)
    assert created_price.provider == "openai"
    assert created_price.model == "gpt-4.1-mini"
    assert created_price.input_usd_per_1m_tokens == Decimal("0.4000000000")
    assert created_price.output_usd_per_1m_tokens == Decimal("1.6000000000")
    assert created_price.cache_read_usd_per_1m_tokens == Decimal("0.1000000000")


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


@pytest.mark.asyncio
async def test_organization_dashboard_composes_usage_and_control_signals(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    async def organization_usage_summary(*args, **kwargs):
        assert kwargs["organization_id"] == organization_id
        return service.UsageSummaryResponse(
            window=service.UsageSummaryWindow(
                startDate=date(2026, 7, 1),
                endDate=date(2026, 7, 10),
                timezone="UTC",
                breakdownLimit=8,
            ),
            summary=service.UsageSummaryTotals(
                requests=10,
                succeeded=9,
                failed=1,
                running=0,
                inputTokens=1000,
                outputTokens=500,
                totalTokens=1500,
                costUsd=Decimal("1.00"),
                toolCalls=20,
            ),
            byUser=[],
            byWorkspace=[],
            byAgent=[
                service.UsageSummaryBreakdownRow(
                    id=str(agent_id),
                    label="Triage agent",
                    requests=4,
                    inputTokens=400,
                    outputTokens=200,
                    totalTokens=600,
                    costUsd=Decimal("0.40"),
                    toolCalls=12,
                )
            ],
            byModel=[
                service.UsageSummaryBreakdownRow(
                    id="openai:gpt-4.1-mini",
                    label="openai / gpt-4.1-mini",
                    requests=10,
                    inputTokens=1000,
                    outputTokens=500,
                    totalTokens=1500,
                    costUsd=Decimal("1.00"),
                    toolCalls=0,
                )
            ],
            daily=[],
        )

    async def control_counts(*args, **kwargs):
        assert kwargs["organization_id"] == organization_id
        assert kwargs["catalog_stale_before"].tzinfo is not None
        return {
            "workspaces": 1,
            "active_workspaces": 1,
            "members": 3,
            "active_members": 3,
            "agents": 2,
            "active_agents": 1,
            "installed_servers": 3,
            "enabled_servers": 2,
            "servers_needing_attention": 1,
            "server_updates": 1,
            "tools": 9,
            "runtime_sessions": 2,
            "active_runtime_sessions": 1,
            "runtime_sessions_needing_attention": 1,
            "catalog_sources": 2,
            "enabled_catalog_sources": 2,
            "synced_catalog_sources": 1,
            "catalog_errors": 1,
            "stale_catalog_sources": 1,
            "provider_credentials": 1,
            "active_provider_credentials": 1,
            "resource_limits": 2,
            "usage_budgets": 1,
            "monthly_budget_usd": Decimal("10.00"),
        }

    async def tool_totals(*args, **kwargs):
        assert kwargs["started_at_from"] == datetime(2026, 7, 1, tzinfo=UTC)
        assert kwargs["started_at_to"] == datetime(2026, 7, 11, tzinfo=UTC)
        return {
            "tool_calls": 20,
            "failed_tool_calls": 2,
            "running_tool_calls": 0,
            "average_tool_duration_ms": 125.4,
        }

    async def workspace_rows(*args, **kwargs):
        assert kwargs["limit"] == 8
        return [
            {
                "id": workspace_id,
                "name": "Production",
                "slug": "prod",
                "status": "active",
                "requests": 10,
                "failed_requests": 1,
                "total_tokens": 1500,
                "cost_usd": Decimal("1.00"),
                "tool_calls": 20,
                "failed_tool_calls": 2,
                "agents": 2,
                "active_agents": 1,
                "installations": 3,
                "enabled_installations": 2,
                "servers_needing_attention": 1,
                "server_updates": 1,
                "tool_count": 9,
                "runtime_sessions": 2,
                "active_runtime_sessions": 1,
                "runtime_sessions_needing_attention": 1,
                "latest_activity_at": datetime(2026, 7, 10, 12, tzinfo=UTC),
            }
        ]

    async def runtime_rows(*args, **kwargs):
        return [{"runtime": "remote", "total": 3, "enabled": 2, "attention": 1}]

    async def provider_rows(*args, **kwargs):
        return [{"provider": "openai", "total": 1, "active": 1, "api_key": 1, "oauth": 0}]

    async def top_tool_rows(*args, **kwargs):
        return [
            {
                "server_name": "acme/github",
                "tool_name": "search_issues",
                "workspace_id": workspace_id,
                "workspace_name": "Production",
                "calls": 20,
                "failed": 2,
                "average_duration_ms": 125.4,
                "p95_duration_ms": 320,
                "last_called_at": datetime(2026, 7, 10, 12, tzinfo=UTC),
            }
        ]

    monkeypatch.setattr(service, "organization_usage_summary", organization_usage_summary)
    monkeypatch.setattr(service.repository, "organization_dashboard_control_counts", control_counts)
    monkeypatch.setattr(
        service.repository,
        "organization_dashboard_tool_usage_totals",
        tool_totals,
    )
    monkeypatch.setattr(
        service.repository,
        "organization_dashboard_workspace_rows",
        workspace_rows,
    )
    monkeypatch.setattr(
        service.repository,
        "organization_dashboard_runtime_rows",
        runtime_rows,
    )
    monkeypatch.setattr(
        service.repository,
        "organization_dashboard_provider_rows",
        provider_rows,
    )
    monkeypatch.setattr(
        service.repository,
        "organization_dashboard_top_tool_rows",
        top_tool_rows,
    )

    response = await service.organization_dashboard(
        object(),
        organization_id=organization_id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 10),
    )

    assert response.summary.health_score == 74
    assert response.summary.projected_monthly_cost_usd == Decimal("3.000000")
    assert response.summary.budget_utilization_percent == 30.0
    assert response.summary.request_success_rate == 90.0
    assert response.summary.tool_success_rate == 90.0
    assert response.summary.average_tool_duration_ms == 125
    assert response.workspaces[0].name == "Production"
    assert response.runtime_mix[0].label == "Remote endpoints"
    assert response.providers[0].provider == "openai"
    assert response.top_tools[0].error_rate == 10.0
    assert response.top_tools[0].p95_duration_ms == 320
    assert {item.key for item in response.attention} >= {
        "catalog-errors",
        "mcp-servers",
        "runtime-sessions",
        "tool-failures",
    }


@pytest.mark.asyncio
async def test_workspace_observability_dashboard_composes_triage_signals(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    run_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async def workspace_usage_summary(*args, **kwargs):
        assert kwargs["organization_id"] == organization_id
        assert kwargs["workspace_id"] == workspace_id
        return service.UsageSummaryResponse(
            window=service.UsageSummaryWindow(
                startDate=date(2026, 7, 1),
                endDate=date(2026, 7, 10),
                timezone="UTC",
                breakdownLimit=8,
            ),
            summary=service.UsageSummaryTotals(
                requests=5,
                succeeded=4,
                failed=1,
                running=0,
                inputTokens=1000,
                outputTokens=400,
                totalTokens=1400,
                costUsd=Decimal("0.42"),
                toolCalls=9,
            ),
            byUser=[
                service.UsageSummaryBreakdownRow(
                    id=str(user_id),
                    label="Asha Rao",
                    requests=5,
                    inputTokens=1000,
                    outputTokens=400,
                    totalTokens=1400,
                    costUsd=Decimal("0.42"),
                    toolCalls=9,
                )
            ],
            byWorkspace=[],
            byAgent=[
                service.UsageSummaryBreakdownRow(
                    id=str(agent_id),
                    label="Triage agent",
                    requests=5,
                    inputTokens=1000,
                    outputTokens=400,
                    totalTokens=1400,
                    costUsd=Decimal("0.42"),
                    toolCalls=9,
                )
            ],
            byModel=[
                service.UsageSummaryBreakdownRow(
                    id="openai:gpt-4.1-mini",
                    label="openai / gpt-4.1-mini",
                    requests=5,
                    inputTokens=1000,
                    outputTokens=400,
                    totalTokens=1400,
                    costUsd=Decimal("0.42"),
                    toolCalls=0,
                )
            ],
            daily=[],
        )

    async def control_counts(*args, **kwargs):
        assert kwargs["started_at_from"] == datetime(2026, 7, 1, tzinfo=UTC)
        assert kwargs["started_at_to"] == datetime(2026, 7, 11, tzinfo=UTC)
        return {
            "agent_runs": 3,
            "failed_agent_runs": 1,
            "running_agent_runs": 1,
            "active_runtime_sessions": 2,
            "runtime_sessions_needing_attention": 1,
        }

    async def tool_totals(*args, **kwargs):
        assert kwargs["started_at_from"] == datetime(2026, 7, 1, tzinfo=UTC)
        assert kwargs["started_at_to"] == datetime(2026, 7, 11, tzinfo=UTC)
        return {
            "tool_calls": 9,
            "failed_tool_calls": 2,
            "running_tool_calls": 1,
            "attributed_tool_calls": 8,
            "unattributed_tool_calls": 1,
            "average_tool_duration_ms": 1450.4,
            "p95_tool_duration_ms": 6200,
        }

    async def top_tool_rows(*args, **kwargs):
        return [
            {
                "server_name": "acme/github",
                "tool_name": "search_issues",
                "calls": 9,
                "failed": 2,
                "average_duration_ms": 1450.4,
                "p95_duration_ms": 6200,
                "last_called_at": datetime(2026, 7, 10, 12, tzinfo=UTC),
            }
        ]

    async def llm_attribution_counts(*args, **kwargs):
        assert kwargs["started_at_from"] == datetime(2026, 7, 1, tzinfo=UTC)
        assert kwargs["started_at_to"] == datetime(2026, 7, 11, tzinfo=UTC)
        return {
            "attributed_llm_calls": 4,
            "unattributed_llm_calls": 1,
        }

    async def recent_run_rows(*args, **kwargs):
        return [
            {
                "id": run_id,
                "agent_id": agent_id,
                "agent_name": "Triage agent",
                "triggered_by_id": user_id,
                "triggered_by_email": "asha@example.com",
                "first_name": "Asha",
                "last_name": "Rao",
                "trigger_type": "chat",
                "status": "failed",
                "requests": 5,
                "failed_requests": 1,
                "input_tokens": 1000,
                "output_tokens": 400,
                "cost_usd": Decimal("0.42"),
                "tool_calls": 9,
                "failed_tool_calls": 2,
                "trace_id": "trace-1",
                "span_id": "span-1",
                "started_at": datetime(2026, 7, 10, 12, tzinfo=UTC),
                "finished_at": datetime(2026, 7, 10, 12, 1, tzinfo=UTC),
                "error": "Provider timeout",
            }
        ]

    monkeypatch.setattr(service, "workspace_usage_summary", workspace_usage_summary)
    monkeypatch.setattr(
        service.repository,
        "workspace_observability_control_counts",
        control_counts,
    )
    monkeypatch.setattr(
        service.repository,
        "workspace_observability_tool_usage_totals",
        tool_totals,
    )
    monkeypatch.setattr(
        service.repository,
        "workspace_observability_llm_attribution_counts",
        llm_attribution_counts,
    )
    monkeypatch.setattr(
        service.repository,
        "workspace_observability_top_tool_rows",
        top_tool_rows,
    )
    monkeypatch.setattr(
        service.repository,
        "workspace_observability_recent_run_rows",
        recent_run_rows,
    )

    response = await service.workspace_observability_dashboard(
        object(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 10),
    )

    assert response.summary.health_score < 100
    assert response.summary.tool_calls == 9
    assert response.summary.p95_tool_duration_ms == 6200
    assert response.summary.unattributed_llm_calls == 1
    assert response.recent_runs[0].trace_id == "trace-1"
    assert response.recent_runs[0].triggered_by_display_name == "Asha Rao"
    assert response.top_tools[0].error_rate == 22.2
    assert {item.key for item in response.attention} >= {
        f"run-{run_id}",
        "tool-failures",
        "slow-tools",
    }


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
