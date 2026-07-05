from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.llm_providers import service
from app.modules.llm_providers.exceptions import (
    DuplicateLLMProviderCredentialError,
    InvalidLLMProviderCredentialAuthError,
    InvalidLLMProviderCredentialScopeError,
)
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.schemas import (
    LLMProviderCredentialCreate,
    LLMProviderCredentialUpdate,
    LLMProviderModelRead,
)
from app.modules.organizations.models import Organization, OrganizationMembership
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            instance.created_at = now
            instance.updated_at = now

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        instance.created_at = getattr(instance, "created_at", now)
        instance.updated_at = now

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)


def patch_resolved_secrets(monkeypatch, values: dict) -> None:
    async def resolve_secret(*args, **kwargs):
        handle_id = args[2]
        return SimpleNamespace(value=values[handle_id])

    monkeypatch.setattr(service, "resolve_secret", resolve_secret)


@pytest.mark.asyncio
async def test_org_admin_can_create_provider_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def no_duplicate(*args, **kwargs):
        return None

    validated_secrets: list[str] = []
    secret_handle_id = uuid4()
    secret_store_id = uuid4()
    secret_write_calls: list[dict] = []
    secret_handle_calls: list[object] = []

    async def validate_openai_api_key(secret_value: str):
        validated_secrets.append(secret_value)

    monkeypatch.setattr(
        service.require_organization_admin.__globals__["repository"],
        "get_organization_by_id",
        get_organization_by_id,
    )
    monkeypatch.setattr(
        service.require_organization_admin.__globals__["repository"],
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(service.repository, "get_credential_by_name", no_duplicate)
    monkeypatch.setattr(service, "validate_openai_api_key", validate_openai_api_key)

    async def write_secret_values(*args, **kwargs):
        secret_write_calls.append({"args": args, "kwargs": kwargs})

    async def create_secret_handle(*args, **kwargs):
        payload = args[3]
        secret_handle_calls.append(payload)
        return SimpleNamespace(id=secret_handle_id)

    monkeypatch.setattr(service, "write_secret_values", write_secret_values)
    monkeypatch.setattr(service, "create_secret_handle", create_secret_handle)

    session = FakeSession()
    response = await service.create_provider_credential(
        session,
        user,
        organization_id,
        LLMProviderCredentialCreate(
            name=" Primary OpenAI ",
            provider=" OpenAI ",
            apiKeySecretStoreId=secret_store_id,
            apiKey="sk-test",
        ),
    )

    credential = session.added[0]
    assert isinstance(credential, LLMProviderCredential)
    assert credential.name == "Primary OpenAI"
    assert credential.provider == "openai"
    assert credential.api_key_secret_handle_id == secret_handle_id
    assert credential.auth_method == "api_key"
    assert credential.visibility == "organization"
    assert response.api_key_secret_handle_id == secret_handle_id
    assert response.auth_method == "api_key"
    assert validated_secrets == ["sk-test"]
    assert secret_write_calls[0]["args"][2] == organization_id
    assert secret_write_calls[0]["args"][3] == secret_store_id
    assert secret_write_calls[0]["kwargs"]["values"] == {"api_key": "sk-test"}
    assert secret_write_calls[0]["kwargs"]["purpose"] == "llm_credential"
    assert secret_handle_calls[0].store_id == secret_store_id
    assert secret_handle_calls[0].key_name == "api_key"
    assert secret_handle_calls[0].purpose == "llm_credential"


@pytest.mark.asyncio
async def test_org_admin_can_create_oauth_provider_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )
    expires_at = service.utc_now() + timedelta(hours=1)
    access_handle_id = uuid4()
    refresh_handle_id = uuid4()

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def no_duplicate(*args, **kwargs):
        return None

    monkeypatch.setattr(
        service.require_organization_admin.__globals__["repository"],
        "get_organization_by_id",
        get_organization_by_id,
    )
    monkeypatch.setattr(
        service.require_organization_admin.__globals__["repository"],
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(service.repository, "get_credential_by_name", no_duplicate)
    patch_resolved_secrets(
        monkeypatch,
        {
            access_handle_id: "access-token",
            refresh_handle_id: "refresh-token",
        },
    )

    session = FakeSession()
    response = await service.create_provider_credential(
        session,
        user,
        organization_id,
        LLMProviderCredentialCreate(
            name="ChatGPT OAuth",
            provider="openai_chatgpt",
            authMethod="oauth",
            oauthProvider="chatgpt",
            oauthAccessTokenSecretHandleId=access_handle_id,
            oauthRefreshTokenSecretHandleId=refresh_handle_id,
            oauthExpiresAt=expires_at,
            oauthScopes=["openid", "profile"],
            oauthMetadata={"tenant": "default"},
        ),
    )

    credential = session.added[0]
    assert isinstance(credential, LLMProviderCredential)
    assert credential.provider == "openai_chatgpt"
    assert credential.auth_method == "oauth"
    assert credential.api_key_secret_handle_id is None
    assert credential.oauth_provider == "chatgpt"
    assert credential.oauth_access_token_secret_handle_id == access_handle_id
    assert credential.oauth_refresh_token_secret_handle_id == refresh_handle_id
    assert response.auth_method == "oauth"
    assert response.oauth_provider == "chatgpt"
    assert response.oauth_expires_at == expires_at
    assert response.oauth_scopes == ["openid", "profile"]
    assert response.oauth_metadata == {"tenant": "default"}
    assert response.api_key_secret_handle_id is None
    assert response.oauth_access_token_secret_handle_id == access_handle_id
    assert response.oauth_refresh_token_secret_handle_id == refresh_handle_id


@pytest.mark.asyncio
async def test_refresh_chatgpt_oauth_credential_writes_shared_secret_document(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    store_id = uuid4()
    access_handle_id = uuid4()
    refresh_handle_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="ChatGPT",
        provider="openai_chatgpt",
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_access_token_secret_handle_id=access_handle_id,
        oauth_refresh_token_secret_handle_id=refresh_handle_id,
        is_active=True,
    )
    store = SimpleNamespace(
        id=store_id,
        provider="openbao",
        workspace_id=None,
        is_active=True,
    )
    access_handle = SimpleNamespace(
        id=access_handle_id,
        store_id=store_id,
        workspace_id=None,
        external_ref="wardn/orgs/acme/chatgpt",
        key_name="access_token",
        purpose="oauth_token",
    )
    refresh_handle = SimpleNamespace(
        id=refresh_handle_id,
        store_id=store_id,
        workspace_id=None,
        external_ref="wardn/orgs/acme/chatgpt",
        key_name="refresh_token",
        purpose="oauth_token",
    )
    writes: list[dict] = []

    async def refresh_chatgpt_oauth_token(refresh_token: str):
        assert refresh_token == "old-refresh"
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    async def get_handle(*args, **kwargs):
        return {
            access_handle_id: access_handle,
            refresh_handle_id: refresh_handle,
        }[kwargs["handle_id"]]

    async def get_store(*args, **kwargs):
        assert kwargs["store_id"] == store_id
        return store

    class FakeProvider:
        async def write(self, store, external_ref, values, context):
            writes.append(
                {
                    "external_ref": external_ref,
                    "values": values,
                    "workspace_id": context.workspace_id,
                }
            )

    monkeypatch.setattr(service, "refresh_chatgpt_oauth_token", refresh_chatgpt_oauth_token)
    monkeypatch.setattr(service.secrets_repository, "get_handle", get_handle)
    monkeypatch.setattr(service.secrets_repository, "get_store", get_store)
    monkeypatch.setattr(service, "get_secret_provider", lambda _provider: FakeProvider())

    secrets = await service.refresh_chatgpt_oauth_credential(
        FakeSession(),
        credential,
        service.ResolvedLLMCredentialSecrets(
            oauth_access_token="old-access",
            oauth_refresh_token="old-refresh",
        ),
    )

    assert secrets.oauth_access_token == "new-access"
    assert secrets.oauth_refresh_token == "new-refresh"
    assert writes == [
        {
            "external_ref": "wardn/orgs/acme/chatgpt",
            "values": {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
            },
            "workspace_id": None,
        }
    ]
    assert credential.oauth_expires_at is not None


@pytest.mark.asyncio
async def test_create_provider_credential_rejects_invalid_openai_api_key(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def no_duplicate(*args, **kwargs):
        return None

    async def reject_openai_api_key(*args, **kwargs):
        raise InvalidLLMProviderCredentialAuthError("OpenAI API key was rejected")
    secret_handle_id = uuid4()

    monkeypatch.setattr(
        service.require_organization_admin.__globals__["repository"],
        "get_organization_by_id",
        get_organization_by_id,
    )
    monkeypatch.setattr(
        service.require_organization_admin.__globals__["repository"],
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(service.repository, "get_credential_by_name", no_duplicate)
    monkeypatch.setattr(service, "validate_openai_api_key", reject_openai_api_key)
    patch_resolved_secrets(monkeypatch, {secret_handle_id: "sk-invalid"})

    session = FakeSession()
    with pytest.raises(InvalidLLMProviderCredentialAuthError):
        await service.create_provider_credential(
            session,
            user,
            organization_id,
                LLMProviderCredentialCreate(
                    name="Primary OpenAI",
                    provider="openai",
                    apiKeySecretHandleId=secret_handle_id,
                ),
        )

    assert session.added == []


@pytest.mark.asyncio
async def test_update_provider_credential_validates_existing_openai_api_key(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    now = datetime(2026, 6, 23, tzinfo=UTC)
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    secret_handle_id = uuid4()
    existing = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="Primary",
        provider="openai",
        visibility="organization",
        auth_method="api_key",
        api_key_secret_handle_id=secret_handle_id,
        base_url="",
        extra_headers={},
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    async def get_credential(*args, **kwargs):
        return existing

    async def get_organization_by_id(*args, **kwargs):
        return Organization(
            id=organization_id,
            name="Default",
            slug="default",
            status="active",
        )

    async def get_organization_membership(*args, **kwargs):
        return None

    validated_secrets: list[str] = []

    async def validate_openai_api_key(secret_value: str):
        validated_secrets.append(secret_value)

    org_repository = service.require_organization_admin.__globals__["repository"]
    monkeypatch.setattr(service.repository, "get_credential", get_credential)
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)
    monkeypatch.setattr(service, "validate_openai_api_key", validate_openai_api_key)
    patch_resolved_secrets(monkeypatch, {secret_handle_id: "sk-existing"})

    response = await service.update_provider_credential(
        FakeSession(),
        user,
        organization_id,
        credential_id,
        LLMProviderCredentialUpdate(isActive=False),
    )

    assert validated_secrets == ["sk-existing"]
    assert existing.is_active is False
    assert response.is_active is False


@pytest.mark.asyncio
async def test_list_provider_credential_models_uses_credential_secret(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    secret_handle_id = uuid4()
    credential = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        auth_method="api_key",
        api_key_secret_handle_id=secret_handle_id,
        base_url="",
        extra_headers={},
        is_active=True,
    )
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def get_credential(*args, **kwargs):
        return credential

    discovered_tokens: list[str] = []

    async def fetch_openai_models(token: str):
        discovered_tokens.append(token)
        return [
            LLMProviderModelRead(id="gpt-4.1", name="gpt-4.1"),
            LLMProviderModelRead(id="gpt-4o-mini", name="gpt-4o-mini"),
        ]

    org_repository = service.require_organization_member.__globals__["repository"]
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)
    monkeypatch.setattr(service.repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "fetch_openai_models", fetch_openai_models)
    patch_resolved_secrets(monkeypatch, {secret_handle_id: "sk-existing"})

    response = await service.list_provider_credential_models(
        FakeSession(),
        user,
        organization_id,
        credential_id,
    )

    assert discovered_tokens == ["sk-existing"]
    assert [model.id for model in response.models] == ["gpt-4.1", "gpt-4o-mini"]


@pytest.mark.asyncio
async def test_validate_provider_credential_resolves_and_checks_secret(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    secret_handle_id = uuid4()
    credential = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        auth_method="api_key",
        api_key_secret_handle_id=secret_handle_id,
        base_url="",
        extra_headers={},
        is_active=True,
    )
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def get_credential(*args, **kwargs):
        return credential

    validated_secrets: list[str] = []

    async def validate_openai_api_key(secret_value: str):
        validated_secrets.append(secret_value)

    org_repository = service.require_organization_member.__globals__["repository"]
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)
    monkeypatch.setattr(service.repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "validate_openai_api_key", validate_openai_api_key)
    patch_resolved_secrets(monkeypatch, {secret_handle_id: "sk-existing"})

    response = await service.validate_provider_credential_by_id(
        FakeSession(),
        user,
        organization_id,
        credential_id,
    )

    assert response.ok is True
    assert response.message == "Credential validation passed."
    assert validated_secrets == ["sk-existing"]


@pytest.mark.asyncio
async def test_validate_provider_credential_returns_false_for_rejected_secret(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    secret_handle_id = uuid4()
    credential = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        auth_method="api_key",
        api_key_secret_handle_id=secret_handle_id,
        base_url="",
        extra_headers={},
        is_active=True,
    )
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def get_credential(*args, **kwargs):
        return credential

    async def reject_openai_api_key(secret_value: str):
        raise InvalidLLMProviderCredentialAuthError("OpenAI API key was rejected")

    org_repository = service.require_organization_member.__globals__["repository"]
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)
    monkeypatch.setattr(service.repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "validate_openai_api_key", reject_openai_api_key)
    patch_resolved_secrets(monkeypatch, {secret_handle_id: "sk-existing"})

    response = await service.validate_provider_credential_by_id(
        FakeSession(),
        user,
        organization_id,
        credential_id,
    )

    assert response.ok is False
    assert response.message == "OpenAI API key was rejected"


@pytest.mark.asyncio
async def test_list_provider_credential_models_uses_chatgpt_catalog(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    access_handle_id = uuid4()
    refresh_handle_id = uuid4()
    credential = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="OpenAI ChatGPT",
        provider="openai_chatgpt",
        visibility="organization",
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_access_token_secret_handle_id=access_handle_id,
        oauth_refresh_token_secret_handle_id=refresh_handle_id,
        base_url="",
        extra_headers={},
        is_active=True,
    )
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    async def get_credential(*args, **kwargs):
        return credential

    async def fail_openai_model_fetch(*args, **kwargs):
        raise AssertionError("ChatGPT OAuth should use the local model catalog")

    org_repository = service.require_organization_member.__globals__["repository"]
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)
    monkeypatch.setattr(service.repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "fetch_openai_models", fail_openai_model_fetch)
    patch_resolved_secrets(
        monkeypatch,
        {
            access_handle_id: "access-token",
            refresh_handle_id: "refresh-token",
        },
    )

    response = await service.list_provider_credential_models(
        FakeSession(),
        user,
        organization_id,
        credential_id,
    )

    assert [model.id for model in response.models] == list(service.OPENAI_CHATGPT_MODEL_IDS)


def test_oauth_auth_rejects_unsupported_provider() -> None:
    with pytest.raises(InvalidLLMProviderCredentialAuthError):
        service.validate_auth_settings(
            auth_method="oauth",
            secret_value="",
            oauth_provider="github",
        )


@pytest.mark.asyncio
async def test_workspace_credential_requires_workspace_id() -> None:
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)

    with pytest.raises(InvalidLLMProviderCredentialScopeError):
        await service.create_provider_credential(
            FakeSession(),
            user,
            uuid4(),
            LLMProviderCredentialCreate(
                name="Workspace key",
                provider="openai",
                visibility="workspace",
                workspaceId=uuid4(),
                apiKeySecretHandleId=uuid4(),
            ).model_copy(update={"workspace_id": None}),
        )


@pytest.mark.asyncio
async def test_update_rejects_duplicate_provider_credential_name(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    secret_handle_id = uuid4()
    existing = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="Primary",
        provider="openai",
        visibility="organization",
        api_key_secret_handle_id=secret_handle_id,
        base_url="",
        extra_headers={},
        is_active=True,
    )
    duplicate = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="Duplicate",
        provider="openai",
        visibility="organization",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )

    async def get_credential(*args, **kwargs):
        return existing

    async def get_credential_by_name(*args, **kwargs):
        return duplicate

    async def get_organization_by_id(*args, **kwargs):
        return Organization(
            id=organization_id,
            name="Default",
            slug="default",
            status="active",
        )

    async def get_organization_membership(*args, **kwargs):
        return None

    org_repository = service.require_organization_admin.__globals__["repository"]
    monkeypatch.setattr(service.repository, "get_credential", get_credential)
    monkeypatch.setattr(service.repository, "get_credential_by_name", get_credential_by_name)
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)

    with pytest.raises(DuplicateLLMProviderCredentialError):
        await service.update_provider_credential(
            FakeSession(),
            user,
            organization_id,
            credential_id,
            LLMProviderCredentialUpdate(name="Duplicate"),
        )
