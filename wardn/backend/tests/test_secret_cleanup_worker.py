import argparse
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.commands.registry import CommandRegistry
from app.modules.secrets import cleanup_worker, commands, managed_repository
from app.modules.secrets.models import ManagedSecret, SecretStore


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

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
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSessionContext:
        session = FakeSession()
        self.sessions.append(session)
        return FakeSessionContext(session)


def managed_secret() -> ManagedSecret:
    now = datetime.now(UTC)
    return ManagedSecret(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=None,
        store_id=uuid.uuid4(),
        created_by_id=uuid.uuid4(),
        owner_type="llm_provider_credential",
        owner_id=uuid.uuid4(),
        purpose="llm_credential",
        external_ref="wardn/test/credential",
        status="cleaning",
        cleanup_available_at=now,
        cleanup_attempt_count=1,
        cleanup_max_attempts=10,
        cleanup_worker_id="worker-1",
        cleanup_error="",
        created_at=now,
        updated_at=now,
    )


def test_cleanup_claim_uses_skip_locked_and_excludes_attached_provisioning() -> None:
    now = datetime.now(UTC)
    statement = managed_repository.claimable_cleanup_statement(
        now=now,
        stale_before=now,
    )

    sql = str(statement.compile(dialect=postgresql.dialect())).upper()

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "NOT (EXISTS" in sql
    rendered = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "cleanup_pending" in rendered


@pytest.mark.asyncio
async def test_cleanup_deletes_external_path_before_database_state(monkeypatch) -> None:
    resource = managed_secret()
    store = SecretStore(
        id=resource.store_id,
        organization_id=resource.organization_id,
        workspace_id=None,
        provider="openbao",
        name="Secrets",
        config={},
        auth_config={},
        is_active=True,
    )
    calls: list[tuple[str, object]] = []

    async def load_target(*args, **kwargs):
        calls.append(("load", args[1]))
        return resource, store

    async def complete(*args, **kwargs):
        calls.append(("complete", args[1]))
        return True

    class Provider:
        async def delete(self, target_store, external_ref, context):
            calls.append(("delete", external_ref))

    monkeypatch.setattr(cleanup_worker.managed_repository, "load_cleanup_target", load_target)
    monkeypatch.setattr(cleanup_worker.managed_repository, "complete_cleanup", complete)
    monkeypatch.setattr(cleanup_worker, "get_secret_provider", lambda _name: Provider())
    factory = FakeSessionFactory()

    await cleanup_worker.execute_cleanup(
        resource.id,
        worker_id="worker-1",
        attempt=1,
        session_factory=factory,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )

    assert calls == [
        ("load", resource.id),
        ("delete", resource.external_ref),
        ("complete", resource.id),
    ]
    assert all(session.committed for session in factory.sessions)


def test_register_secret_cleanup_command() -> None:
    registry = CommandRegistry()
    commands.register_secret_commands(registry)

    args = registry.build_parser().parse_args(
        ["runsecretcleanup", "--once", "--worker-id", "worker-1", "--poll-interval", "3"]
    )

    assert args == argparse.Namespace(
        command="runsecretcleanup",
        once=True,
        worker_id="worker-1",
        poll_interval=3.0,
        verbose=False,
        handler=commands.handle_runsecretcleanup,
    )
