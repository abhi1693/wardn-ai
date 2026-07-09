import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.observability import router as observability_router
from app.modules.observability import service as observability_service
from app.modules.observability.schemas import (
    LLMModelPriceListResponse,
    LLMModelPricePrefillResponse,
    LLMModelPriceRead,
    LLMUsageListResponse,
    LLMUsageRead,
    LLMUsageSummary,
    MCPToolUsageListResponse,
    MCPToolUsageRead,
    MCPToolUsageSummary,
    UsageSummaryBreakdownRow,
    UsageSummaryResponse,
    UsageSummaryTotals,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

TEST_ORGANIZATION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEST_WORKSPACE_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
TEST_USER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


class FakeSession:
    async def commit(self):
        return None


async def fake_session():
    yield FakeSession()


async def fake_current_user():
    return User(id=TEST_USER_ID, email="admin@example.com", is_superuser=True)


async def fake_require_workspace_member(*args, **kwargs):
    return None


async def fake_require_organization_member(*args, **kwargs):
    return None


async def fake_require_organization_admin(*args, **kwargs):
    return None


def observability_client(*, authenticated: bool = False) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    if authenticated:
        app.dependency_overrides[get_current_user] = fake_current_user
    return TestClient(app)


def workspace_observability_path(suffix: str = "") -> str:
    return (
        f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/workspaces/{TEST_WORKSPACE_ID}"
        f"/observability{suffix}"
    )


def organization_observability_path(suffix: str = "") -> str:
    return f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/observability{suffix}"


def organization_usage_path(suffix: str = "") -> str:
    return f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/usage{suffix}"


def workspace_usage_path(suffix: str = "") -> str:
    return (
        f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/workspaces/{TEST_WORKSPACE_ID}"
        f"/usage{suffix}"
    )


def usage_summary_response() -> UsageSummaryResponse:
    row = UsageSummaryBreakdownRow(
        id=str(TEST_USER_ID),
        label="Test User",
        requests=2,
        inputTokens=100,
        outputTokens=50,
        totalTokens=150,
        costUsd="0.000125",
        toolCalls=3,
    )
    return UsageSummaryResponse(
        summary=UsageSummaryTotals(
            requests=2,
            succeeded=2,
            failed=0,
            running=0,
            inputTokens=100,
            outputTokens=50,
            totalTokens=150,
            costUsd="0.000125",
            toolCalls=3,
        ),
        byUser=[row],
        byWorkspace=[],
        byAgent=[],
        byModel=[],
    )


def tool_usage_response() -> MCPToolUsageListResponse:
    return MCPToolUsageListResponse(
        summary=MCPToolUsageSummary(
            total=1,
            succeeded=1,
            failed=0,
            running=0,
            attributed=1,
            unattributed=0,
            averageDurationMs=123,
        ),
        toolCalls=[
            MCPToolUsageRead(
                id=uuid.uuid4(),
                organizationId=TEST_ORGANIZATION_ID,
                workspaceId=TEST_WORKSPACE_ID,
                runtimeSessionId=uuid.uuid4(),
                installationId=uuid.uuid4(),
                userId=uuid.uuid4(),
                userEmail="user@example.com",
                userDisplayName="Test User",
                agentId=uuid.uuid4(),
                agentName="Workspace Assistant",
                agentRunId=uuid.uuid4(),
                serverName="io.github.example/weather",
                serverVersion="1.0.0",
                toolName="get_forecast",
                status="succeeded",
                startedAt=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
                finishedAt=datetime(2026, 7, 9, 12, 0, 1, tzinfo=UTC),
                durationMs=123,
                inputSizeBytes=42,
                outputSizeBytes=84,
                isError=False,
                error="",
            )
        ],
    )


def llm_usage_response() -> LLMUsageListResponse:
    return LLMUsageListResponse(
        summary=LLMUsageSummary(
            totalCalls=1,
            succeeded=1,
            failed=0,
            running=0,
            inputTokens=100,
            outputTokens=50,
            totalTokens=150,
            totalCostUsd="0.000125",
            attributed=1,
            unattributed=0,
        ),
        records=[
            LLMUsageRead(
                id=uuid.uuid4(),
                organizationId=TEST_ORGANIZATION_ID,
                workspaceId=TEST_WORKSPACE_ID,
                userId=uuid.uuid4(),
                userEmail="user@example.com",
                userDisplayName="Test User",
                agentId=uuid.uuid4(),
                agentName="Workspace Assistant",
                agentRunId=uuid.uuid4(),
                provider="openai",
                model="gpt-4.1-mini",
                inputTokens=100,
                outputTokens=50,
                totalTokens=150,
                costUsd="0.000125",
                startedAt=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
                finishedAt=datetime(2026, 7, 9, 12, 0, 1, tzinfo=UTC),
                status="succeeded",
                traceId="trace-1",
                spanId="span-1",
                error="",
            )
        ],
    )


def model_prices_response() -> LLMModelPriceListResponse:
    return LLMModelPriceListResponse(
        prices=[
            LLMModelPriceRead(
                id=uuid.uuid4(),
                provider="openai",
                model="gpt-4.1-mini",
                inputUsdPer1mTokens="0.40",
                outputUsdPer1mTokens="1.60",
                cacheReadUsdPer1mTokens="0.10",
                cacheWriteUsdPer1mTokens=None,
                createdAt=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
                updatedAt=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
            )
        ]
    )


def model_price_prefill_response() -> LLMModelPricePrefillResponse:
    return LLMModelPricePrefillResponse(
        found=True,
        provider="openai",
        model="gpt-4.1-mini",
        inputUsdPer1mTokens="0.40",
        outputUsdPer1mTokens="1.60",
        cacheReadUsdPer1mTokens="0.10",
        cacheWriteUsdPer1mTokens="0.50",
        source="openrouter",
        sourceModelId="openai/gpt-4.1-mini",
        sourceModelName="OpenAI: GPT-4.1 Mini",
    )


def test_organization_usage_summary_route(monkeypatch) -> None:
    seen = {}

    async def organization_usage_summary(session, *, organization_id):
        seen["organization_id"] = organization_id
        return usage_summary_response()

    monkeypatch.setattr(
        observability_router,
        "require_organization_admin",
        fake_require_organization_admin,
    )
    monkeypatch.setattr(
        observability_service,
        "organization_usage_summary",
        organization_usage_summary,
    )

    response = observability_client(authenticated=True).get(
        organization_usage_path("/summary")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["costUsd"] == "0.000125"
    assert payload["byUser"][0]["toolCalls"] == 3
    assert seen == {"organization_id": TEST_ORGANIZATION_ID}


def test_workspace_usage_summary_route(monkeypatch) -> None:
    seen = {}

    async def workspace_usage_summary(session, *, organization_id, workspace_id):
        seen["organization_id"] = organization_id
        seen["workspace_id"] = workspace_id
        return usage_summary_response()

    monkeypatch.setattr(
        observability_router,
        "require_workspace_member",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(
        observability_service,
        "workspace_usage_summary",
        workspace_usage_summary,
    )

    response = observability_client(authenticated=True).get(workspace_usage_path("/summary"))

    assert response.status_code == 200
    assert response.json()["summary"]["totalTokens"] == 150
    assert seen == {
        "organization_id": TEST_ORGANIZATION_ID,
        "workspace_id": TEST_WORKSPACE_ID,
    }


def test_me_usage_summary_route(monkeypatch) -> None:
    seen = {}

    async def user_usage_summary(session, *, user_id):
        seen["user_id"] = user_id
        return usage_summary_response()

    monkeypatch.setattr(observability_service, "user_usage_summary", user_usage_summary)

    response = observability_client(authenticated=True).get("/api/v1/me/usage")

    assert response.status_code == 200
    assert response.json()["byUser"][0]["label"] == "Test User"
    assert seen == {"user_id": TEST_USER_ID}


def test_list_mcp_tool_usage_route(monkeypatch) -> None:
    seen = {}

    async def list_workspace_mcp_tool_usage(
        session,
        *,
        organization_id,
        workspace_id,
        limit=100,
    ):
        seen["organization_id"] = organization_id
        seen["workspace_id"] = workspace_id
        seen["limit"] = limit
        return tool_usage_response()

    monkeypatch.setattr(
        observability_router,
        "require_workspace_member",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(
        observability_service,
        "list_workspace_mcp_tool_usage",
        list_workspace_mcp_tool_usage,
    )

    response = observability_client(authenticated=True).get(
        workspace_observability_path("/mcp-tool-usage?limit=25")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["averageDurationMs"] == 123
    assert payload["toolCalls"][0]["userDisplayName"] == "Test User"
    assert payload["toolCalls"][0]["agentName"] == "Workspace Assistant"
    assert seen == {
        "organization_id": TEST_ORGANIZATION_ID,
        "workspace_id": TEST_WORKSPACE_ID,
        "limit": 25,
    }


def test_list_llm_usage_route(monkeypatch) -> None:
    seen = {}

    async def list_workspace_llm_usage(
        session,
        *,
        organization_id,
        workspace_id,
        limit=100,
    ):
        seen["organization_id"] = organization_id
        seen["workspace_id"] = workspace_id
        seen["limit"] = limit
        return llm_usage_response()

    monkeypatch.setattr(
        observability_router,
        "require_workspace_member",
        fake_require_workspace_member,
    )
    monkeypatch.setattr(
        observability_service,
        "list_workspace_llm_usage",
        list_workspace_llm_usage,
    )

    response = observability_client(authenticated=True).get(
        workspace_observability_path("/llm-usage?limit=25")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["totalCalls"] == 1
    assert payload["summary"]["totalCostUsd"] == "0.000125"
    assert payload["records"][0]["model"] == "gpt-4.1-mini"
    assert payload["records"][0]["agentName"] == "Workspace Assistant"
    assert seen == {
        "organization_id": TEST_ORGANIZATION_ID,
        "workspace_id": TEST_WORKSPACE_ID,
        "limit": 25,
    }


def test_list_llm_model_prices_route(monkeypatch) -> None:
    async def list_llm_model_prices(session):
        return model_prices_response()

    monkeypatch.setattr(
        observability_router,
        "require_organization_member",
        fake_require_organization_member,
    )
    monkeypatch.setattr(
        observability_service,
        "list_llm_model_prices",
        list_llm_model_prices,
    )

    response = observability_client(authenticated=True).get(
        organization_observability_path("/llm/model-prices")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["prices"][0]["provider"] == "openai"
    assert payload["prices"][0]["inputUsdPer1mTokens"] == "0.40"


def test_create_llm_model_price_route(monkeypatch) -> None:
    seen = {}

    async def create_llm_model_price(session, payload):
        seen["provider"] = payload.provider
        seen["model"] = payload.model
        return model_prices_response().prices[0]

    monkeypatch.setattr(
        observability_router,
        "require_organization_admin",
        fake_require_organization_admin,
    )
    monkeypatch.setattr(
        observability_service,
        "create_llm_model_price",
        create_llm_model_price,
    )

    response = observability_client(authenticated=True).post(
        organization_observability_path("/llm/model-prices"),
        json={
            "provider": "OpenAI",
            "model": "gpt-4.1-mini",
            "inputUsdPer1mTokens": "0.40",
            "outputUsdPer1mTokens": "1.60",
        },
    )

    assert response.status_code == 201
    assert response.json()["model"] == "gpt-4.1-mini"
    assert seen == {"provider": "OpenAI", "model": "gpt-4.1-mini"}


def test_prefill_llm_model_price_route(monkeypatch) -> None:
    seen = {}

    async def fetch_openrouter_model_prices(*, provider, model):
        seen["provider"] = provider
        seen["model"] = model
        return model_price_prefill_response()

    monkeypatch.setattr(
        observability_router,
        "require_organization_member",
        fake_require_organization_member,
    )
    monkeypatch.setattr(
        observability_service,
        "fetch_openrouter_model_prices",
        fetch_openrouter_model_prices,
    )

    response = observability_client(authenticated=True).get(
        organization_observability_path(
            "/llm/model-prices/prefill?provider=openai&model=gpt-4.1-mini"
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["source"] == "openrouter"
    assert payload["inputUsdPer1mTokens"] == "0.40"
    assert seen == {"provider": "openai", "model": "gpt-4.1-mini"}
