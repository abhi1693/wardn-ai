import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.core.security import verify_password
from app.modules.users import service
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidLoginError,
    OIDCAuthenticationError,
    UserAPITokenNotFoundError,
    UserNotFoundError,
)
from app.modules.users.models import LocalAuthCredential, User, UserAPIToken
from app.modules.users.oidc import OIDCIdentity
from app.modules.users.schemas import (
    LoginRequest,
    UserAPITokenCreate,
    UserAPITokenUpdate,
    UserCreate,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False
        self.committed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)


@pytest.mark.asyncio
async def test_create_user_normalizes_email_and_creates_local_credentials(monkeypatch) -> None:
    async def no_existing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", no_existing_user)
    session = FakeSession()
    payload = UserCreate(
        email=" Admin@Example.COM ",
        first_name=" Ada ",
        last_name=" Lovelace ",
        password=SecretStr("correct horse battery staple"),
    )

    user = await service.create_user(session, payload, is_superuser=True)

    assert user.email == "admin@example.com"
    assert user.first_name == "Ada"
    assert user.last_name == "Lovelace"
    assert user.is_active is True
    assert user.is_superuser is True
    assert user.local_credentials is not None
    assert verify_password("correct horse battery staple", user.local_credentials.password_hash)
    assert session.added == [user]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email(monkeypatch) -> None:
    async def existing_user(*args, **kwargs):
        return User(email="admin@example.com")

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)

    with pytest.raises(DuplicateUserError):
        await service.create_user(
            FakeSession(),
            UserCreate(
                email="admin@example.com",
                password=SecretStr("correct horse battery staple"),
            ),
        )


@pytest.mark.asyncio
async def test_bootstrap_superuser_rejects_existing_users(monkeypatch) -> None:
    async def existing_user_count(*args, **kwargs):
        return 1

    monkeypatch.setattr(service.repository, "count_users", existing_user_count)

    with pytest.raises(BootstrapUserExistsError):
        await service.bootstrap_superuser(
            FakeSession(),
            UserCreate(
                email="admin@example.com",
                password=SecretStr("correct horse battery staple"),
            ),
        )


@pytest.mark.asyncio
async def test_bootstrap_superuser_commits_first_user(monkeypatch) -> None:
    async def no_users(*args, **kwargs):
        return 0

    async def no_existing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "count_users", no_users)
    monkeypatch.setattr(service.repository, "get_user_by_email", no_existing_user)
    session = FakeSession()

    user = await service.bootstrap_superuser(
        session,
        UserCreate(
            email="admin@example.com",
            password=SecretStr("correct horse battery staple"),
        ),
    )

    assert user.is_superuser is True
    assert session.committed is True
    assert session.refreshed == [user]


@pytest.mark.asyncio
async def test_create_user_api_token(monkeypatch) -> None:
    user_id = uuid.uuid4()

    async def existing_user(*args, **kwargs):
        return User(id=user_id, email="admin@example.com")

    monkeypatch.setattr(service.repository, "get_user_by_id", existing_user)
    monkeypatch.setattr(service, "generate_api_token", lambda: ("abc123", "wardn_abc123.secret"))
    monkeypatch.setattr(service, "hash_api_token", lambda token: f"hashed:{token}")
    session = FakeSession()

    record, plaintext = await service.create_user_api_token(
        session,
        user_id,
        UserAPITokenCreate(name="automation", description="local automation"),
    )

    assert plaintext == "wardn_abc123.secret"
    assert record.user_id == user_id
    assert record.name == "automation"
    assert record.description == "local automation"
    assert record.token_prefix == "abc123"
    assert record.token_hash == "hashed:wardn_abc123.secret"
    assert record.organization_ids == []
    assert record.workspace_ids == []
    assert record.is_active is True
    assert session.added == [record]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_create_user_api_token_stores_validated_scopes(monkeypatch) -> None:
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    user = User(id=user_id, email="admin@example.com")

    async def existing_user(*args, **kwargs):
        return user

    async def require_organization_admin(*args, **kwargs):
        assert args[2] == organization_id

    async def get_workspace_by_id(*args, **kwargs):
        assert args[1] == workspace_id
        return type("Workspace", (), {"organization_id": organization_id})()

    async def require_workspace_member(*args, **kwargs):
        assert args[2] == organization_id
        assert args[3] == workspace_id

    monkeypatch.setattr(service.repository, "get_user_by_id", existing_user)
    monkeypatch.setattr(service, "require_organization_admin", require_organization_admin)
    monkeypatch.setattr(
        service.organizations_repository,
        "get_workspace_by_id",
        get_workspace_by_id,
    )
    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service, "generate_api_token", lambda: ("abc123", "wardn_abc123.secret"))
    monkeypatch.setattr(service, "hash_api_token", lambda token: f"hashed:{token}")

    record, _plaintext = await service.create_user_api_token(
        FakeSession(),
        user_id,
        UserAPITokenCreate(
            name="agent",
            organizationIds=[organization_id],
            workspaceIds=[workspace_id],
        ),
    )

    assert record.organization_ids == [str(organization_id)]
    assert record.workspace_ids == [str(workspace_id)]


@pytest.mark.asyncio
async def test_create_user_api_token_requires_existing_user(monkeypatch) -> None:
    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_id", missing_user)

    with pytest.raises(UserNotFoundError):
        await service.create_user_api_token(
            FakeSession(),
            uuid.uuid4(),
            UserAPITokenCreate(name="automation"),
        )


@pytest.mark.asyncio
async def test_list_user_api_tokens_delegates_to_repository(monkeypatch) -> None:
    user_id = uuid.uuid4()
    tokens = [UserAPIToken(id=uuid.uuid4(), user_id=user_id, name="agent")]

    async def list_tokens(*args, **kwargs):
        assert args[1] == user_id
        return tokens

    monkeypatch.setattr(service.repository, "list_user_api_tokens", list_tokens)

    assert await service.list_user_api_tokens(FakeSession(), user_id) == tokens


@pytest.mark.asyncio
async def test_update_user_api_token_updates_fields_and_scopes(monkeypatch) -> None:
    user_id = uuid.uuid4()
    token_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    user = User(id=user_id, email="admin@example.com")
    token = UserAPIToken(
        id=token_id,
        user_id=user_id,
        name="old",
        description="old description",
        organization_ids=[],
        workspace_ids=[],
        is_active=True,
    )

    async def existing_user(*args, **kwargs):
        return user

    async def existing_token(*args, **kwargs):
        assert args[1] == user_id
        assert args[2] == token_id
        return token

    async def require_organization_admin(*args, **kwargs):
        assert args[2] == organization_id

    async def get_workspace_by_id(*args, **kwargs):
        assert args[1] == workspace_id
        return type("Workspace", (), {"organization_id": organization_id})()

    async def require_workspace_member(*args, **kwargs):
        assert args[2] == organization_id
        assert args[3] == workspace_id

    monkeypatch.setattr(service.repository, "get_user_by_id", existing_user)
    monkeypatch.setattr(service.repository, "get_user_api_token_by_id", existing_token)
    monkeypatch.setattr(service, "require_organization_admin", require_organization_admin)
    monkeypatch.setattr(
        service.organizations_repository,
        "get_workspace_by_id",
        get_workspace_by_id,
    )
    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    session = FakeSession()

    result = await service.update_user_api_token(
        session,
        user_id,
        token_id,
        UserAPITokenUpdate(
            name="new",
            description="updated",
            organizationIds=[organization_id],
            workspaceIds=[workspace_id],
            is_active=False,
        ),
    )

    assert result is token
    assert token.name == "new"
    assert token.description == "updated"
    assert token.organization_ids == [str(organization_id)]
    assert token.workspace_ids == [str(workspace_id)]
    assert token.is_active is False
    assert session.flushed is True


@pytest.mark.asyncio
async def test_update_user_api_token_requires_owned_token(monkeypatch) -> None:
    user_id = uuid.uuid4()

    async def existing_user(*args, **kwargs):
        return User(id=user_id, email="admin@example.com")

    async def missing_token(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_id", existing_user)
    monkeypatch.setattr(service.repository, "get_user_api_token_by_id", missing_token)

    with pytest.raises(UserAPITokenNotFoundError):
        await service.update_user_api_token(
            FakeSession(),
            user_id,
            uuid.uuid4(),
            UserAPITokenUpdate(name="new"),
        )


@pytest.mark.asyncio
async def test_delete_user_api_token(monkeypatch) -> None:
    user_id = uuid.uuid4()
    token_id = uuid.uuid4()

    async def delete_token(*args, **kwargs):
        assert args[1] == user_id
        assert args[2] == token_id
        return True

    monkeypatch.setattr(service.repository, "delete_user_api_token", delete_token)

    await service.delete_user_api_token(FakeSession(), user_id, token_id)


@pytest.mark.asyncio
async def test_delete_user_api_token_requires_owned_token(monkeypatch) -> None:
    async def delete_token(*args, **kwargs):
        return False

    monkeypatch.setattr(service.repository, "delete_user_api_token", delete_token)

    with pytest.raises(UserAPITokenNotFoundError):
        await service.delete_user_api_token(FakeSession(), uuid.uuid4(), uuid.uuid4())


def test_is_token_expired() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert service.is_token_expired(UserAPIToken(expires_at=now - timedelta(seconds=1)), now=now)
    assert not service.is_token_expired(
        UserAPIToken(expires_at=now + timedelta(seconds=1)),
        now=now,
    )
    assert not service.is_token_expired(UserAPIToken(expires_at=None), now=now)


def test_is_token_active(monkeypatch) -> None:
    monkeypatch.setattr(service, "verify_api_token", lambda token, token_hash: token_hash == token)
    active_token = UserAPIToken(is_active=True, token_hash="secret", expires_at=None)
    inactive_token = UserAPIToken(is_active=False, token_hash="secret", expires_at=None)

    assert service.is_token_active(active_token, "secret")
    assert not service.is_token_active(active_token, "wrong")
    assert not service.is_token_active(inactive_token, "secret")


@pytest.mark.asyncio
async def test_authenticate_local_user_accepts_valid_credentials(monkeypatch) -> None:
    user = User(
        email="admin@example.com",
        is_active=True,
        local_credentials=LocalAuthCredential(
            password_hash="hashed-password",
            password_updated_at=datetime.now(UTC),
        ),
    )

    async def existing_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)
    monkeypatch.setattr(service, "verify_password", lambda password, hashed: password == "valid")
    session = FakeSession()

    result = await service.authenticate_local_user(
        session,
        LoginRequest(email="ADMIN@example.com", password=SecretStr("valid")),
    )

    assert result == user
    assert user.last_login_at is not None
    assert session.flushed is True


@pytest.mark.asyncio
async def test_authenticate_local_user_rejects_invalid_credentials(monkeypatch) -> None:
    user = User(
        email="admin@example.com",
        is_active=True,
        local_credentials=LocalAuthCredential(
            password_hash="hashed-password",
            password_updated_at=datetime.now(UTC),
        ),
    )

    async def existing_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)
    monkeypatch.setattr(service, "verify_password", lambda password, hashed: False)

    with pytest.raises(InvalidLoginError):
        await service.authenticate_local_user(
            FakeSession(),
            LoginRequest(email="admin@example.com", password=SecretStr("invalid")),
        )


@pytest.mark.asyncio
async def test_authenticate_oidc_identity_creates_user(monkeypatch) -> None:
    async def no_existing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", no_existing_user)
    session = FakeSession()

    user = await service.authenticate_oidc_identity(
        session,
        OIDCIdentity(
            email=" Admin@Example.COM ",
            first_name="Ada",
            last_name="Lovelace",
            subject="subject-1",
        ),
        auto_create_users=True,
        superuser_emails=["admin@example.com"],
    )

    assert user.email == "admin@example.com"
    assert user.first_name == "Ada"
    assert user.last_name == "Lovelace"
    assert user.is_active is True
    assert user.is_superuser is True
    assert user.local_credentials is None
    assert user.last_login_at is not None
    assert session.added == [user]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_authenticate_oidc_identity_updates_existing_user(monkeypatch) -> None:
    user = User(
        email="admin@example.com",
        first_name="Old",
        last_name="Name",
        is_active=True,
        is_superuser=False,
    )

    async def existing_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)

    result = await service.authenticate_oidc_identity(
        FakeSession(),
        OIDCIdentity(
            email="admin@example.com",
            first_name="Ada",
            last_name="Lovelace",
            subject="subject-1",
        ),
        auto_create_users=True,
        superuser_emails=["admin@example.com"],
    )

    assert result is user
    assert user.first_name == "Ada"
    assert user.last_name == "Lovelace"
    assert user.is_superuser is True
    assert user.last_login_at is not None


@pytest.mark.asyncio
async def test_authenticate_oidc_identity_rejects_missing_user_when_auto_create_disabled(
    monkeypatch,
) -> None:
    async def no_existing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", no_existing_user)

    with pytest.raises(OIDCAuthenticationError):
        await service.authenticate_oidc_identity(
            FakeSession(),
            OIDCIdentity(
                email="admin@example.com",
                first_name="Ada",
                last_name="Lovelace",
                subject="subject-1",
            ),
            auto_create_users=False,
            superuser_emails=[],
        )
