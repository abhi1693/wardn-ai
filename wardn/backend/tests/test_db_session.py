import uuid
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.db import session as db_session
from app.modules.users import service as users_service


class FakeTransaction:
    def __init__(self) -> None:
        self.entered = False
        self.exit_exception: type[BaseException] | None = None

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.exit_exception = exc_type


class FakeSession:
    def __init__(self) -> None:
        self.transaction = FakeTransaction()
        self.flushed = False

    def begin(self) -> FakeTransaction:
        return self.transaction

    async def flush(self) -> None:
        self.flushed = True


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeSessionFactory:
    def __init__(self) -> None:
        self.session = FakeSession()

    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext(self.session)


def test_database_engine_uses_configured_pool_settings(monkeypatch) -> None:
    captured = {}
    expected_engine = object()

    def create_async_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return expected_engine

    settings = SimpleNamespace(
        database_url=SecretStr("postgresql+asyncpg://wardn:secret@db/wardn"),
        database_pool_size=7,
        database_max_overflow=11,
        database_pool_timeout_seconds=12.5,
        database_pool_recycle_seconds=900,
        database_pool_pre_ping=True,
        database_pool_use_lifo=True,
    )
    monkeypatch.setattr(db_session, "create_async_engine", create_async_engine)

    assert db_session.create_database_engine(settings) is expected_engine
    assert captured == {
        "url": "postgresql+asyncpg://wardn:secret@db/wardn",
        "pool_size": 7,
        "max_overflow": 11,
        "pool_timeout": 12.5,
        "pool_recycle": 900,
        "pool_pre_ping": True,
        "pool_use_lifo": True,
    }


@pytest.mark.asyncio
async def test_request_session_commits_flushed_changes_after_success(monkeypatch) -> None:
    session_factory = FakeSessionFactory()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", session_factory)
    dependency = db_session.get_db_session()

    assert await anext(dependency) is session_factory.session
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert session_factory.session.transaction.entered is True
    assert session_factory.session.transaction.exit_exception is None


@pytest.mark.asyncio
async def test_request_session_rolls_back_when_request_fails(monkeypatch) -> None:
    session_factory = FakeSessionFactory()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", session_factory)
    dependency = db_session.get_db_session()

    assert await anext(dependency) is session_factory.session
    with pytest.raises(RuntimeError, match="request failed"):
        await dependency.athrow(RuntimeError("request failed"))

    assert session_factory.session.transaction.exit_exception is RuntimeError


@pytest.mark.asyncio
async def test_read_only_api_token_authentication_commits_last_used_at(monkeypatch) -> None:
    session_factory = FakeSessionFactory()
    token = SimpleNamespace(user_id=uuid.uuid4(), last_used_at=None)
    user = SimpleNamespace(id=token.user_id, is_active=True)

    async def get_api_token_by_prefix(*args, **kwargs):
        return token

    async def get_user_by_id(*args, **kwargs):
        return user

    monkeypatch.setattr(db_session, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(
        users_service.repository,
        "get_api_token_by_prefix",
        get_api_token_by_prefix,
    )
    monkeypatch.setattr(users_service.repository, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(users_service, "is_token_active", lambda *args, **kwargs: True)
    dependency = db_session.get_db_session()
    session = await anext(dependency)

    authenticated = await users_service.authenticate_api_token(session, "wardn_key.secret")
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert authenticated == (user, token)
    assert token.last_used_at is not None
    assert session.flushed is True
    assert session.transaction.exit_exception is None
