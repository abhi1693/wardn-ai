from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

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

    async def clear_defaults(*args, **kwargs):
        return None

    validated_secrets: list[str] = []

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
    monkeypatch.setattr(service.repository, "clear_default_credentials", clear_defaults)
    monkeypatch.setattr(service, "validate_openai_api_key", validate_openai_api_key)

    session = FakeSession()
    response = await service.create_provider_credential(
        session,
        user,
        organization_id,
        LLMProviderCredentialCreate(
            name=" Primary OpenAI ",
            provider=" OpenAI ",
            secret=SecretStr("sk-test"),
            isDefault=True,
        ),
    )

    credential = session.added[0]
    assert isinstance(credential, LLMProviderCredential)
    assert credential.name == "Primary OpenAI"
    assert credential.provider == "openai"
    assert credential.secret_value == "sk-test"
    assert credential.auth_method == "api_key"
    assert credential.visibility == "organization"
    assert response.has_secret is True
    assert response.auth_method == "api_key"
    assert response.is_default is True
    assert validated_secrets == ["sk-test"]


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
    expires_at = datetime(2026, 7, 1, tzinfo=UTC)

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
            oauthAccessToken=SecretStr("access-token"),
            oauthRefreshToken=SecretStr("refresh-token"),
            oauthExpiresAt=expires_at,
            oauthScopes=["openid", "profile"],
            oauthMetadata={"tenant": "default"},
        ),
    )

    credential = session.added[0]
    assert isinstance(credential, LLMProviderCredential)
    assert credential.provider == "openai_chatgpt"
    assert credential.auth_method == "oauth"
    assert credential.secret_value == ""
    assert credential.oauth_provider == "chatgpt"
    assert credential.oauth_access_token == "access-token"
    assert credential.oauth_refresh_token == "refresh-token"
    assert response.auth_method == "oauth"
    assert response.oauth_provider == "chatgpt"
    assert response.oauth_expires_at == expires_at
    assert response.oauth_scopes == ["openid", "profile"]
    assert response.oauth_metadata == {"tenant": "default"}
    assert response.has_secret is False
    assert response.has_oauth_access_token is True
    assert response.has_oauth_refresh_token is True


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

    session = FakeSession()
    with pytest.raises(InvalidLLMProviderCredentialAuthError):
        await service.create_provider_credential(
            session,
            user,
            organization_id,
            LLMProviderCredentialCreate(
                name="Primary OpenAI",
                provider="openai",
                secret=SecretStr("sk-invalid"),
            ),
        )

    assert session.added == []


@pytest.mark.asyncio
async def test_update_provider_credential_validates_existing_openai_api_key(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    now = datetime(2026, 6, 23, tzinfo=UTC)
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    existing = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="Primary",
        provider="openai",
        visibility="organization",
        auth_method="api_key",
        secret_value="sk-existing",
        base_url="",
        extra_headers={},
        is_default=False,
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
    credential = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        auth_method="api_key",
        secret_value="sk-existing",
        base_url="",
        extra_headers={},
        is_default=False,
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

    response = await service.list_provider_credential_models(
        FakeSession(),
        user,
        organization_id,
        credential_id,
    )

    assert discovered_tokens == ["sk-existing"]
    assert [model.id for model in response.models] == ["gpt-4.1", "gpt-4o-mini"]


@pytest.mark.asyncio
async def test_list_provider_credential_models_uses_chatgpt_catalog(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="OpenAI ChatGPT",
        provider="openai_chatgpt",
        visibility="organization",
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_access_token="access-token",
        oauth_refresh_token="refresh-token",
        base_url="",
        extra_headers={},
        is_default=False,
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
                secret=SecretStr("sk-test"),
            ).model_copy(update={"workspace_id": None}),
        )


@pytest.mark.asyncio
async def test_update_rejects_duplicate_provider_credential_name(monkeypatch) -> None:
    organization_id = uuid4()
    credential_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    existing = LLMProviderCredential(
        id=credential_id,
        organization_id=organization_id,
        name="Primary",
        provider="openai",
        visibility="organization",
        secret_value="sk-test",
        base_url="",
        extra_headers={},
        is_default=False,
        is_active=True,
    )
    duplicate = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="Duplicate",
        provider="openai",
        visibility="organization",
        secret_value="sk-other",
        base_url="",
        extra_headers={},
        is_default=False,
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
