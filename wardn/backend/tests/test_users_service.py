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
    UserNotFoundError,
)
from app.modules.users.models import LocalAuthCredential, User, UserAPIToken
from app.modules.users.schemas import LoginRequest, UserAPITokenCreate, UserCreate


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
    assert record.is_active is True
    assert session.added == [record]
    assert session.flushed is True


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
