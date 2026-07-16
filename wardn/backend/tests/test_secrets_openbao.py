from uuid import uuid4

import pytest

from app.core.outbound_http import UnsafeOutboundURLError
from app.modules.secrets.exceptions import InvalidSecretStoreError
from app.modules.secrets.models import SecretHandle, SecretStore
from app.modules.secrets.provider import SecretResolutionContext
from app.modules.secrets.providers.openbao import OpenBaoSecretProvider, OpenBaoToken
from app.modules.secrets.providers.openbao_profiles import (
    OpenBaoAuthProfile,
    read_profile_file,
)


def kubernetes_provider(tmp_path) -> OpenBaoSecretProvider:
    return OpenBaoSecretProvider(
        auth_profiles={
            "production": OpenBaoAuthProfile.model_validate(
                {
                    "baseUrl": "https://bao.example.com",
                    "method": "kubernetes",
                    "role": "wardn-prod",
                    "tokenFile": "token",
                }
            )
        },
        auth_file_root=str(tmp_path),
        url_validator=lambda _url: None,
    )


def approle_provider(tmp_path) -> OpenBaoSecretProvider:
    return OpenBaoSecretProvider(
        auth_profiles={
            "production": OpenBaoAuthProfile.model_validate(
                {
                    "baseUrl": "https://bao.example.com",
                    "method": "approle",
                    "roleIdFile": "role_id",
                    "secretIdFile": "secret_id",
                    "namespace": "org-namespace",
                }
            )
        },
        auth_file_root=str(tmp_path),
        url_validator=lambda _url: None,
    )


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeAsyncClient:
    requests: list[tuple[str, str, dict | None]] = []
    client_options: list[dict] = []
    delete_status_code = 204

    def __init__(self, *args, **kwargs) -> None:
        self.client_options.append(kwargs)

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

    async def delete(self, url, *, headers=None):
        self.requests.append(("DELETE", url, None))
        assert headers["X-Vault-Token"] == "bao-token"
        return FakeResponse(self.delete_status_code, {})


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


class FakeInvalidLoginAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, *, headers=None, json=None):
        return FakeResponse(400, {"errors": ["invalid role_id or secret_id"]})


class FakeAuthRetryAsyncClient:
    requests: list[tuple[str, str, dict | None, str | None]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, *, headers=None, json=None):
        token = headers.get("X-Vault-Token") if headers else None
        self.requests.append(("POST", url, json, token))
        return FakeResponse(
            200,
            {
                "auth": {
                    "client_token": "fresh-token",
                    "renewable": True,
                    "lease_duration": 3600,
                }
            },
        )

    async def get(self, url, *, headers=None, params=None):
        token = headers.get("X-Vault-Token") if headers else None
        self.requests.append(("GET", url, params, token))
        if token == "stale-token":
            return FakeResponse(403, {"errors": ["permission denied"]})
        assert token == "fresh-token"
        return FakeResponse(
            200,
            {
                "data": {
                    "data": {"api_token": "hub-token"},
                    "metadata": {"version": 8},
                }
            },
        )


@pytest.mark.asyncio
async def test_openbao_resolves_kv_v2_secret(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("service-account-jwt", encoding="utf-8")
    FakeAsyncClient.requests = []
    FakeAsyncClient.client_options = []
    monkeypatch.setattr("app.modules.secrets.providers.openbao.httpx.AsyncClient", FakeAsyncClient)

    organization_id = uuid4()
    workspace_id = uuid4()
    provider = kubernetes_provider(tmp_path)
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider="openbao",
        name="Production OpenBao",
        config={
            "baseUrl": "https://bao.example.com",
            "kvMount": "secret",
        },
        auth_config={"profile": "production"},
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
    assert all(options["follow_redirects"] is False for options in FakeAsyncClient.client_options)


@pytest.mark.asyncio
async def test_openbao_retries_read_with_fresh_token_after_auth_failure(
    monkeypatch,
    tmp_path,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("service-account-jwt", encoding="utf-8")
    FakeAuthRetryAsyncClient.requests = []
    monkeypatch.setattr(
        "app.modules.secrets.providers.openbao.httpx.AsyncClient",
        FakeAuthRetryAsyncClient,
    )

    organization_id = uuid4()
    provider = kubernetes_provider(tmp_path)
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://bao.example.com", "kvMount": "secret"},
        auth_config={"profile": "production"},
        is_active=True,
    )
    provider._token_cache[provider._cache_key(store, provider._auth_settings(store))] = (
        OpenBaoToken(token="stale-token")
    )
    handle = SecretHandle(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        store_id=store.id,
        purpose="catalog_source",
        display_name="Wardn Hub token",
        external_ref="wardn/orgs/acme/catalog-sources/wardn-hub",
        key_name="api_token",
        version="",
    )

    result = await provider.resolve(
        store,
        handle,
        SecretResolutionContext(
            organization_id=str(organization_id),
            purpose="catalog_source",
        ),
    )

    assert result.value == "hub-token"
    assert result.version == "8"
    assert FakeAuthRetryAsyncClient.requests == [
        (
            "GET",
            "https://bao.example.com/v1/secret/data/wardn/orgs/acme/catalog-sources/wardn-hub",
            {},
            "stale-token",
        ),
        (
            "POST",
            "https://bao.example.com/v1/auth/kubernetes/login",
            {"role": "wardn-prod", "jwt": "service-account-jwt"},
            None,
        ),
        (
            "GET",
            "https://bao.example.com/v1/secret/data/wardn/orgs/acme/catalog-sources/wardn-hub",
            {},
            "fresh-token",
        ),
    ]


@pytest.mark.asyncio
async def test_openbao_writes_kv_v2_secret(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("service-account-jwt", encoding="utf-8")
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.modules.secrets.providers.openbao.httpx.AsyncClient", FakeAsyncClient)

    organization_id = uuid4()
    provider = kubernetes_provider(tmp_path)
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://bao.example.com", "kvMount": "secret"},
        auth_config={"profile": "production"},
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
async def test_openbao_deletes_kv_v2_metadata_idempotently(monkeypatch, tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("service-account-jwt", encoding="utf-8")
    FakeAsyncClient.requests = []
    FakeAsyncClient.delete_status_code = 404
    monkeypatch.setattr("app.modules.secrets.providers.openbao.httpx.AsyncClient", FakeAsyncClient)

    organization_id = uuid4()
    provider = kubernetes_provider(tmp_path)
    store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://bao.example.com", "kvMount": "secret"},
        auth_config={"profile": "production"},
        is_active=True,
    )

    await provider.delete(
        store,
        "wardn/orgs/acme/chatgpt",
        SecretResolutionContext(
            organization_id=str(organization_id),
            purpose="oauth_token",
        ),
    )

    assert FakeAsyncClient.requests == [
        (
            "POST",
            "https://bao.example.com/v1/auth/kubernetes/login",
            {"role": "wardn-prod", "jwt": "service-account-jwt"},
        ),
        (
            "DELETE",
            "https://bao.example.com/v1/secret/metadata/wardn/orgs/acme/chatgpt",
            None,
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

    provider = approle_provider(tmp_path)
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
        },
        auth_config={"profile": "production"},
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
async def test_openbao_validate_connection_includes_login_error_detail(
    monkeypatch,
    tmp_path,
) -> None:
    role_id_file = tmp_path / "role_id"
    secret_id_file = tmp_path / "secret_id"
    role_id_file.write_text("role-id", encoding="utf-8")
    secret_id_file.write_text("secret-id", encoding="utf-8")
    monkeypatch.setattr(
        "app.modules.secrets.providers.openbao.httpx.AsyncClient",
        FakeInvalidLoginAsyncClient,
    )

    provider = approle_provider(tmp_path)
    store = SecretStore(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://bao.example.com"},
        auth_config={"profile": "production"},
        is_active=True,
    )

    result = await provider.validate_connection(store)

    assert result.ok is False
    assert result.message == "OpenBao login failed with HTTP 400: invalid role_id or secret_id"


@pytest.mark.asyncio
async def test_openbao_rejects_base_url_that_does_not_match_profile(tmp_path) -> None:
    provider = kubernetes_provider(tmp_path)
    store = SecretStore(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://attacker.example.com"},
        auth_config={"profile": "production"},
        is_active=True,
    )

    result = await provider.validate_store(store)

    assert result.ok is False
    assert result.message == (
        "OpenBao baseUrl must match the operator-defined authentication profile"
    )


def test_openbao_profile_file_rejects_symlink_outside_operator_root(tmp_path) -> None:
    credential_root = tmp_path / "credentials"
    credential_root.mkdir()
    outside_file = tmp_path / "backend-secret"
    outside_file.write_text("do-not-read", encoding="utf-8")
    (credential_root / "token").symlink_to(outside_file)

    with pytest.raises(
        InvalidSecretStoreError,
        match="must be inside the operator credential root",
    ):
        read_profile_file(str(credential_root), "token", "Kubernetes service account token")


@pytest.mark.asyncio
async def test_openbao_store_applies_outbound_url_policy(tmp_path) -> None:
    profile = OpenBaoAuthProfile.model_validate(
        {
            "baseUrl": "https://bao.internal:8200",
            "method": "kubernetes",
            "role": "wardn-prod",
            "tokenFile": "token",
        }
    )

    def reject_url(_url: str) -> None:
        raise UnsafeOutboundURLError("outbound URL resolves to a non-public address")

    provider = OpenBaoSecretProvider(
        auth_profiles={"production": profile},
        auth_file_root=str(tmp_path),
        url_validator=reject_url,
    )
    store = SecretStore(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=None,
        provider="openbao",
        name="Production OpenBao",
        config={"baseUrl": "https://bao.internal:8200"},
        auth_config={"profile": "production"},
        is_active=True,
    )

    result = await provider.validate_store(store)

    assert result.ok is False
    assert result.message == (
        "OpenBao baseUrl was rejected: outbound URL resolves to a non-public address"
    )
