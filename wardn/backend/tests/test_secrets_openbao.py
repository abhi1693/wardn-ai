from uuid import uuid4

import pytest

from app.modules.secrets.models import SecretHandle, SecretStore
from app.modules.secrets.provider import SecretResolutionContext
from app.modules.secrets.providers.openbao import OpenBaoSecretProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeAsyncClient:
    requests: list[tuple[str, str, dict | None]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, *, headers=None, json=None):
        self.requests.append(("POST", url, json))
        if url.endswith("/data/wardn/orgs/acme/chatgpt"):
            assert headers["X-Vault-Token"] == "bao-token"
            return FakeResponse(200, {"data": {"version": 4}})
        return FakeResponse(
            200,
            {
                "auth": {
                    "client_token": "bao-token",
                    "renewable": True,
                    "lease_duration": 3600,
                }
            },
        )

    async def get(self, url, *, headers=None, params=None):
        self.requests.append(("GET", url, params))
        assert headers["X-Vault-Token"] == "bao-token"
        return FakeResponse(
            200,
            {
                "data": {
                    "data": {"api_key": "sk-test"},
                    "metadata": {"version": 3},
                }
            },
        )


class FakeValidationAsyncClient:
    requests: list[tuple[str, str, dict | None]] = []
    marker: str = ""
    expected_namespace: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, *, headers=None, json=None):
        self.requests.append(("POST", url, json))
        if self.expected_namespace:
            assert headers["X-Vault-Namespace"] == self.expected_namespace
        if url.endswith("/auth/approle/login"):
            return FakeResponse(
                200,
                {
                    "auth": {
                        "client_token": "bao-token",
                        "renewable": True,
                        "lease_duration": 3600,
                    }
                },
            )
        assert headers["X-Vault-Token"] == "bao-token"
        assert json is not None
        self.__class__.marker = json["data"]["wardn_validation"]
        return FakeResponse(200, {"data": {"version": 1}})

    async def get(self, url, *, headers=None, params=None):
        self.requests.append(("GET", url, params))
        assert headers["X-Vault-Token"] == "bao-token"
        if self.expected_namespace:
            assert headers["X-Vault-Namespace"] == self.expected_namespace
        return FakeResponse(
            200,
            {"data": {"data": {"wardn_validation": self.marker}, "metadata": {"version": 1}}},
        )

    async def delete(self, url, *, headers=None):
        self.requests.append(("DELETE", url, None))
        assert headers["X-Vault-Token"] == "bao-token"
        if self.expected_namespace:
            assert headers["X-Vault-Namespace"] == self.expected_namespace
        return FakeResponse(204, {})


@pytest.mark.asyncio
async def test_openbao_resolves_kv_v2_secret(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("service-account-jwt", encoding="utf-8")
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.modules.secrets.providers.openbao.httpx.AsyncClient", FakeAsyncClient)

    organization_id = uuid4()
    workspace_id = uuid4()
    provider = OpenBaoSecretProvider()
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider="openbao",
        name="Production OpenBao",
        config={
            "baseUrl": "https://bao.example.com",
            "kvMount": "secret",
            "authMount": "kubernetes",
        },
        auth_config={
            "method": "kubernetes",
            "role": "wardn-prod",
            "serviceAccountTokenPath": str(token_file),
        },
        is_active=True,
    )
    handle = SecretHandle(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        store_id=store.id,
        purpose="llm_credential",
        display_name="OpenAI",
        external_ref="wardn/orgs/acme/workspaces/prod/openai",
        key_name="api_key",
        version="",
    )

    result = await provider.resolve(
        store,
        handle,
        SecretResolutionContext(
            organization_id=str(organization_id),
            workspace_id=str(workspace_id),
            purpose="llm_credential",
        ),
    )

    assert result.value == "sk-test"
    assert result.version == "3"
    assert FakeAsyncClient.requests == [
        ("POST", "https://bao.example.com/v1/auth/kubernetes/login", {
            "role": "wardn-prod",
            "jwt": "service-account-jwt",
        }),
        (
            "GET",
            "https://bao.example.com/v1/secret/data/wardn/orgs/acme/workspaces/prod/openai",
            {},
        ),
    ]


@pytest.mark.asyncio
async def test_openbao_writes_kv_v2_secret(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("service-account-jwt", encoding="utf-8")
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.modules.secrets.providers.openbao.httpx.AsyncClient", FakeAsyncClient)

    organization_id = uuid4()
    provider = OpenBaoSecretProvider()
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://bao.example.com", "kvMount": "secret"},
        auth_config={
            "method": "kubernetes",
            "role": "wardn-prod",
            "serviceAccountTokenPath": str(token_file),
        },
        is_active=True,
    )

    result = await provider.write(
        store,
        "wardn/orgs/acme/chatgpt",
        {"access_token": "access", "refresh_token": "refresh"},
        SecretResolutionContext(organization_id=str(organization_id), purpose="oauth_token"),
    )

    assert result.version == "4"
    assert FakeAsyncClient.requests == [
        (
            "POST",
            "https://bao.example.com/v1/auth/kubernetes/login",
            {"role": "wardn-prod", "jwt": "service-account-jwt"},
        ),
        (
            "POST",
            "https://bao.example.com/v1/secret/data/wardn/orgs/acme/chatgpt",
            {"data": {"access_token": "access", "refresh_token": "refresh"}},
        ),
    ]


@pytest.mark.asyncio
async def test_openbao_validate_connection_logs_in_with_approle(monkeypatch, tmp_path) -> None:
    role_id_file = tmp_path / "role_id"
    secret_id_file = tmp_path / "secret_id"
    role_id_file.write_text("role-id", encoding="utf-8")
    secret_id_file.write_text("secret-id", encoding="utf-8")
    FakeValidationAsyncClient.requests = []
    FakeValidationAsyncClient.marker = ""
    FakeValidationAsyncClient.expected_namespace = "org-namespace"
    monkeypatch.setattr(
        "app.modules.secrets.providers.openbao.httpx.AsyncClient",
        FakeValidationAsyncClient,
    )

    provider = OpenBaoSecretProvider()
    organization_id = uuid4()
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={
            "baseUrl": "https://bao.example.com",
            "kvMount": "secret",
            "namespace": FakeValidationAsyncClient.expected_namespace,
        },
        auth_config={
            "method": "approle",
            "roleIdFile": str(role_id_file),
            "secretIdFile": str(secret_id_file),
        },
        is_active=True,
    )

    result = await provider.validate_connection(store)

    assert result.ok is True
    assert "wrote, read, and deleted" in result.message
    assert FakeValidationAsyncClient.requests[0] == (
        "POST",
        "https://bao.example.com/v1/auth/approle/login",
        {"role_id": "role-id", "secret_id": "secret-id"},
    )
    assert FakeValidationAsyncClient.requests[1][0] == "POST"
    assert FakeValidationAsyncClient.requests[1][1].startswith(
        f"https://bao.example.com/v1/secret/data/wardn/orgs/{organization_id}/validation/"
    )
    assert FakeValidationAsyncClient.requests[2][0] == "GET"
    assert FakeValidationAsyncClient.requests[2][1].startswith(
        f"https://bao.example.com/v1/secret/data/wardn/orgs/{organization_id}/validation/"
    )
    assert FakeValidationAsyncClient.requests[3][0] == "DELETE"
    assert FakeValidationAsyncClient.requests[3][1].startswith(
        f"https://bao.example.com/v1/secret/metadata/wardn/orgs/{organization_id}/validation/"
    )


@pytest.mark.asyncio
async def test_openbao_rejects_http_url_when_tls_verify_is_enabled(tmp_path) -> None:
    role_id_file = tmp_path / "role_id"
    secret_id_file = tmp_path / "secret_id"
    role_id_file.write_text("role-id", encoding="utf-8")
    secret_id_file.write_text("secret-id", encoding="utf-8")

    provider = OpenBaoSecretProvider()
    store = SecretStore(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "http://bao.example.com", "tlsVerify": True},
        auth_config={
            "method": "approle",
            "roleIdFile": str(role_id_file),
            "secretIdFile": str(secret_id_file),
        },
        is_active=True,
    )

    result = await provider.validate_store(store)

    assert result.ok is False
    assert result.message == "Verify TLS requires an HTTPS OpenBao URL"
