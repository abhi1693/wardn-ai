import httpx
import pytest

from app.modules.llm_providers import provider_clients
from app.modules.llm_providers.exceptions import InvalidLLMProviderCredentialAuthError


def mock_chatgpt_api(monkeypatch, handler):
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        provider_clients.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_chatgpt_models_uses_account_and_preserves_visible_provider_order(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {"slug": "hidden-model", "visibility": "hide"},
                    {"slug": "gpt-future", "display_name": "Newest model", "visibility": "list"},
                    {
                        "slug": "subscription-model",
                        "display_name": "Subscription model",
                        "visibility": "list",
                        "supported_in_api": False,
                    },
                    {"slug": " gpt-future ", "display_name": "Duplicate", "visibility": "list"},
                    {"slug": "gpt-older", "display_name": " ", "visibility": "list"},
                    {"slug": "not-selectable", "visibility": "unknown"},
                    {"slug": "missing-visibility"},
                    {"slug": "  ", "visibility": "list"},
                    {"slug": 123, "visibility": "list"},
                    "invalid",
                    None,
                ]
            },
        )

    mock_chatgpt_api(monkeypatch, handle)
    models = await provider_clients.fetch_chatgpt_models("access-token", account_id="account-123")

    assert [(model.id, model.name) for model in models] == [
        ("gpt-future", "Newest model"),
        ("subscription-model", "Subscription model"),
        ("gpt-older", "gpt-older"),
    ]
    assert len(requests) == 1
    request = requests[0]
    assert request.url.copy_with(query=None) == provider_clients.CHATGPT_MODELS_URL
    assert dict(request.url.params) == {"client_version": provider_clients.CODEX_COMPAT_VERSION}
    assert request.headers["Authorization"] == "Bearer access-token"
    assert request.headers["ChatGPT-Account-ID"] == "account-123"
    assert request.headers["originator"] == provider_clients.CODEX_COMPAT_ORIGINATOR
    assert request.headers["User-Agent"] == provider_clients.CODEX_COMPAT_USER_AGENT


@pytest.mark.asyncio
async def test_chatgpt_models_does_not_reuse_another_accounts_catalog(monkeypatch):
    requests = []

    def handle(request):
        account = request.headers["ChatGPT-Account-ID"]
        requests.append((account, request.headers["Authorization"]))
        return httpx.Response(
            200, json={"models": [{"slug": f"model-{account}", "visibility": "list"}]}
        )

    mock_chatgpt_api(monkeypatch, handle)
    first = await provider_clients.fetch_chatgpt_models("token-a", account_id="a")
    second = await provider_clients.fetch_chatgpt_models("token-b", account_id="b")
    assert [model.id for model in first] == ["model-a"]
    assert [model.id for model in second] == ["model-b"]
    assert requests == [("a", "Bearer token-a"), ("b", "Bearer token-b")]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500, 503])
async def test_chatgpt_models_reports_upstream_errors_without_payloads_or_redirects(
    monkeypatch, status
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://untrusted.example/models"},
            text="Sensitive upstream error body containing access-token",
        )

    mock_chatgpt_api(monkeypatch, handle)
    message = (
        "ChatGPT credential was rejected"
        if status in {401, 403}
        else f"ChatGPT model discovery failed with HTTP {status}"
    )
    with pytest.raises(InvalidLLMProviderCredentialAuthError) as error:
        await provider_clients.fetch_chatgpt_models("access-token", account_id="account")
    assert str(error.value) == message
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], {}, {"data": []}, {"models": {}}, {"models": None}])
async def test_chatgpt_models_rejects_invalid_envelopes(monkeypatch, payload):
    mock_chatgpt_api(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(InvalidLLMProviderCredentialAuthError, match="response is invalid"):
        await provider_clients.fetch_chatgpt_models("access-token", account_id="account")


@pytest.mark.asyncio
async def test_chatgpt_models_rejects_invalid_json(monkeypatch):
    mock_chatgpt_api(monkeypatch, lambda request: httpx.Response(200, text="<html>Invalid</html>"))
    with pytest.raises(InvalidLLMProviderCredentialAuthError, match="response is invalid"):
        await provider_clients.fetch_chatgpt_models("access-token", account_id="account")


@pytest.mark.asyncio
async def test_chatgpt_models_accepts_empty_catalog_without_static_fallback(monkeypatch):
    mock_chatgpt_api(monkeypatch, lambda request: httpx.Response(200, json={"models": []}))
    assert await provider_clients.fetch_chatgpt_models("access-token", account_id="account") == []


@pytest.mark.asyncio
async def test_chatgpt_models_reports_network_timeout(monkeypatch):
    def handle(request):
        raise httpx.ReadTimeout("timed out", request=request)

    mock_chatgpt_api(monkeypatch, handle)
    with pytest.raises(InvalidLLMProviderCredentialAuthError, match="could not reach ChatGPT"):
        await provider_clients.fetch_chatgpt_models("access-token", account_id="account")


@pytest.mark.asyncio
async def test_chatgpt_models_requires_an_account_before_sending_credentials(monkeypatch):
    def handle(request):
        pytest.fail("Discovery must not send credentials without an account")

    mock_chatgpt_api(monkeypatch, handle)
    with pytest.raises(InvalidLLMProviderCredentialAuthError, match="account ID is missing"):
        await provider_clients.fetch_chatgpt_models("access-token", account_id=" ")
