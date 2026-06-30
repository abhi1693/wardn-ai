from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.secrets import repository, service
from app.modules.secrets.exceptions import DuplicateSecretStoreError, InvalidSecretHandleError
from app.modules.secrets.models import SecretHandle, SecretStore
from app.modules.secrets.provider import ResolvedSecret, SecretValidationResult, SecretWriteResult
from app.modules.secrets.schemas import SecretHandleCreate, SecretStoreCreate, SecretStoreUpdate
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        now = datetime(2026, 6, 29, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            instance.created_at = now
            instance.updated_at = now

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 29, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        instance.created_at = getattr(instance, "created_at", now)
        instance.updated_at = now

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)


class FakeProvider:
    name = "openbao"

    async def validate_store(self, store):
        return SecretValidationResult(ok=True, message="ok")

    async def validate_handle(self, store, handle):
        return SecretValidationResult(ok=True, message="ok")

    async def resolve(self, store, handle, context):
        return ResolvedSecret(value="resolved-secret", version="7")

    async def write(self, store, external_ref, values, context):
        return SecretWriteResult(version="8")


@pytest.mark.asyncio
async def test_create_workspace_secret_store(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    required_scopes = []

    async def require_secret_scope_admin(session, current_user, org_id, scope_workspace_id):
        required_scopes.append((current_user.id, org_id, scope_workspace_id))

    async def get_store_by_name(*args, **kwargs):
        return None

    async def list_stores(*args, **kwargs):
        return []

    monkeypatch.setattr(service, "require_secret_scope_admin", require_secret_scope_admin)
    monkeypatch.setattr(repository, "get_store_by_name", get_store_by_name)
    monkeypatch.setattr(repository, "list_stores", list_stores)
    monkeypatch.setattr(service, "get_secret_provider", lambda _provider: FakeProvider())

    session = FakeSession()
    response = await service.create_secret_store(
        session,
        user,
        organization_id,
        SecretStoreCreate(
            name=" Production OpenBao ",
            workspaceId=workspace_id,
            config={"baseUrl": "https://bao.example.com", "kvMount": "secret"},
            authConfig={"method": "kubernetes", "role": "wardn-prod"},
        ),
    )

    store = session.added[0]
    assert isinstance(store, SecretStore)
    assert store.name == "Production OpenBao"
    assert store.provider == "openbao"
    assert store.workspace_id == workspace_id
    assert store.config["baseUrl"] == "https://bao.example.com"
    assert store.auth_config["role"] == "wardn-prod"
    assert response.is_active is True
    assert required_scopes == [(user.id, organization_id, workspace_id)]


@pytest.mark.asyncio
async def test_create_secret_store_rejects_duplicate_org_url(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    existing_store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Org OpenBao",
        config={"baseUrl": "https://bao.example.com/"},
        auth_config={"method": "kubernetes", "role": "wardn-prod"},
        is_active=True,
    )

    async def require_secret_scope_admin(*args, **kwargs):
        return None

    async def get_store_by_name(*args, **kwargs):
        return None

    async def list_stores(*args, **kwargs):
        return [existing_store]

    monkeypatch.setattr(service, "require_secret_scope_admin", require_secret_scope_admin)
    monkeypatch.setattr(repository, "get_store_by_name", get_store_by_name)
    monkeypatch.setattr(repository, "list_stores", list_stores)

    with pytest.raises(DuplicateSecretStoreError, match="URL already exists"):
        await service.create_secret_store(
            FakeSession(),
            user,
            organization_id,
            SecretStoreCreate(
                name="Workspace OpenBao",
                workspaceId=workspace_id,
                config={"baseUrl": " https://bao.example.com "},
                authConfig={"method": "kubernetes", "role": "wardn-prod"},
            ),
        )


@pytest.mark.asyncio
async def test_update_secret_store_rejects_duplicate_org_url(monkeypatch) -> None:
    organization_id = uuid4()
    store_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    store = SecretStore(
        id=store_id,
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Org OpenBao",
        config={"baseUrl": "https://bao-a.example.com"},
        auth_config={"method": "kubernetes", "role": "wardn-prod"},
        is_active=True,
    )
    other_store = SecretStore(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=uuid4(),
        provider="openbao",
        name="Workspace OpenBao",
        config={"baseUrl": "https://bao-b.example.com/"},
        auth_config={"method": "kubernetes", "role": "wardn-prod"},
        is_active=True,
    )

    async def require_secret_scope_admin(*args, **kwargs):
        return None

    async def get_store(*args, **kwargs):
        return store

    async def list_stores(*args, **kwargs):
        return [store, other_store]

    monkeypatch.setattr(service, "require_secret_scope_admin", require_secret_scope_admin)
    monkeypatch.setattr(repository, "get_store", get_store)
    monkeypatch.setattr(repository, "list_stores", list_stores)

    with pytest.raises(DuplicateSecretStoreError, match="URL already exists"):
        await service.update_secret_store(
            FakeSession(),
            user,
            organization_id,
            store_id,
            SecretStoreUpdate(config={"baseUrl": "https://bao-b.example.com"}),
        )


@pytest.mark.asyncio
async def test_create_workspace_handle_rejects_other_workspace_store(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    store_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    store = SecretStore(
        id=store_id,
        organization_id=organization_id,
        workspace_id=other_workspace_id,
        provider="openbao",
        name="Other Workspace OpenBao",
        config={"baseUrl": "https://bao.example.com"},
        auth_config={"method": "kubernetes", "role": "wardn-prod"},
        is_active=True,
    )

    async def require_secret_scope_admin(*args, **kwargs):
        return None

    async def get_store(*args, **kwargs):
        return store

    monkeypatch.setattr(service, "require_secret_scope_admin", require_secret_scope_admin)
    monkeypatch.setattr(repository, "get_store", get_store)

    with pytest.raises(InvalidSecretHandleError, match="workspaces must match"):
        await service.create_secret_handle(
            FakeSession(),
            user,
            organization_id,
            SecretHandleCreate(
                storeId=store_id,
                workspaceId=workspace_id,
                purpose="mcp_env",
                displayName="GitHub Token",
                externalRef="wardn/orgs/acme/workspaces/prod/github",
                keyName="token",
            ),
        )


@pytest.mark.asyncio
async def test_resolve_secret_uses_provider_registry(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    store_id = uuid4()
    handle_id = uuid4()
    store = SecretStore(
        id=store_id,
        organization_id=organization_id,
        workspace_id=None,
        provider="openbao",
        name="Org OpenBao",
        config={"baseUrl": "https://bao.example.com"},
        auth_config={"method": "kubernetes", "role": "wardn-prod"},
        is_active=True,
    )
    handle = SecretHandle(
        id=handle_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        store_id=store_id,
        purpose="llm_credential",
        display_name="OpenAI",
        external_ref="wardn/orgs/acme/workspaces/prod/openai",
        key_name="api_key",
        version="",
    )

    async def get_handle(*args, **kwargs):
        return handle

    async def get_store(*args, **kwargs):
        return store

    monkeypatch.setattr(repository, "get_handle", get_handle)
    monkeypatch.setattr(repository, "get_store", get_store)
    monkeypatch.setattr(service, "get_secret_provider", lambda _provider: FakeProvider())

    result = await service.resolve_secret(
        FakeSession(),
        organization_id,
        handle_id,
        workspace_id=workspace_id,
    )

    assert result.value == "resolved-secret"
    assert result.version == "7"


@pytest.mark.asyncio
async def test_write_secret_values_uses_provider_registry(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    store_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    store = SecretStore(
        id=store_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider="openbao",
        name="Workspace OpenBao",
        config={"baseUrl": "https://bao.example.com"},
        auth_config={"method": "kubernetes", "role": "wardn-prod"},
        is_active=True,
    )
    calls = {}

    async def require_secret_scope_admin(*args, **kwargs):
        calls["scope"] = args[3]

    async def get_store(*args, **kwargs):
        return store

    class RecordingProvider(FakeProvider):
        async def write(self, secret_store, external_ref, values, context):
            calls["store"] = secret_store
            calls["external_ref"] = external_ref
            calls["values"] = values
            calls["context"] = context
            return SecretWriteResult(version="9")

    monkeypatch.setattr(service, "require_secret_scope_admin", require_secret_scope_admin)
    monkeypatch.setattr(repository, "get_store", get_store)
    monkeypatch.setattr(service, "get_secret_provider", lambda _provider: RecordingProvider())

    result = await service.write_secret_values(
        FakeSession(),
        user,
        organization_id,
        store_id,
        workspace_id=workspace_id,
        external_ref="/wardn/orgs/acme/chatgpt/",
        values={"access_token": "access", "": "ignored"},
        purpose="oauth_token",
    )

    assert result.version == "9"
    assert calls["scope"] == workspace_id
    assert calls["store"] is store
    assert calls["external_ref"] == "wardn/orgs/acme/chatgpt"
    assert calls["values"] == {"access_token": "access"}
    assert calls["context"].purpose == "oauth_token"
