import uuid
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.db import session as db_session
from app.modules.users import service as users_service


class FakeSession:
    def __init__(self) -> None:
        self.flushed = False
        self.committed = False
        self.commit_count = 0
        self.rolled_back = False
        self.info = {}

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rolled_back = True


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

    assert session_factory.session.committed is True
    assert session_factory.session.rolled_back is False


@pytest.mark.asyncio
async def test_request_session_rolls_back_when_request_fails(monkeypatch) -> None:
    session_factory = FakeSessionFactory()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", session_factory)
    dependency = db_session.get_db_session()

    assert await anext(dependency) is session_factory.session
    with pytest.raises(RuntimeError, match="request failed"):
        await dependency.athrow(RuntimeError("request failed"))

    assert session_factory.session.committed is False
    assert session_factory.session.rolled_back is True


@pytest.mark.asyncio
async def test_api_token_authentication_does_not_dirty_request_transaction(monkeypatch) -> None:
    session_factory = FakeSessionFactory()
    token = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), last_used_at=None)
    user = SimpleNamespace(id=token.user_id, is_active=True)
    recorded = []

    async def get_api_token_by_prefix(*args, **kwargs):
        return token

    async def get_user_by_id(*args, **kwargs):
        return user

    async def touch_api_token_last_used(session, token_id, *, used_at, update_before):
        recorded.append((session, token_id, used_at, update_before))
        return True

    monkeypatch.setattr(db_session, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(
        users_service.repository,
        "get_api_token_by_prefix",
        get_api_token_by_prefix,
    )
    monkeypatch.setattr(users_service.repository, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(users_service, "is_token_active", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        users_service.repository,
        "touch_api_token_last_used",
        touch_api_token_last_used,
    )
    dependency = db_session.get_db_session()
    session = await anext(dependency)

    authenticated = await users_service.authenticate_api_token(session, "wardn_key.secret")
    assert recorded == []
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert authenticated == (user, token)
    assert len(recorded) == 1
    assert recorded[0][0] is session
    assert recorded[0][1] == token.id
    assert token.last_used_at is None
    assert session.flushed is False
    assert session.committed is True
    assert session.commit_count == 2
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_recent_api_token_usage_is_not_queued(monkeypatch) -> None:
    used_at = users_service.datetime.now(users_service.UTC)
    token = SimpleNamespace(
        id=uuid.uuid4(),
        last_used_at=used_at - users_service.timedelta(minutes=1),
    )
    session = FakeSession()

    monkeypatch.setattr(
        users_service,
        "get_settings",
        lambda: SimpleNamespace(api_token_usage_update_interval_seconds=300),
    )
    queued = users_service.defer_api_token_usage_update(
        session,
        token,
        now=used_at,
    )

    assert queued is False
    assert session.info == {}
