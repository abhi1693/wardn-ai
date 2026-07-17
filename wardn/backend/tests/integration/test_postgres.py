import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.base import Base, import_models
from app.db.session import run_deferred_session_work
from app.modules.limits.exceptions import LimitExceededError
from app.modules.limits.models import ResourceLimit
from app.modules.limits.service import WORKSPACES_PER_ORGANIZATION
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.mcp_registry import repository as mcp_registry_repository
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.mcp_registry.source_metadata_rate_limit import (
    consume_repository_metadata_rate_limit,
)
from app.modules.mcp_runtime import repository as mcp_runtime_repository
from app.modules.mcp_runtime.models import (
    MCPRuntimeEvent,
    MCPRuntimeSession,
    MCPToolInvocation,
)
from app.modules.organizations import repository as organization_repository
from app.modules.organizations import service as organization_service
from app.modules.organizations.exceptions import DuplicateOrganizationError
from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.schemas import OrganizationCreate, WorkspaceCreate
from app.modules.secrets import managed as managed_secrets_service
from app.modules.secrets import service as secrets_service
from app.modules.secrets.exceptions import SecretInUseError
from app.modules.secrets.models import ManagedSecret, SecretHandle, SecretStore
from app.modules.secrets.provider import SecretWriteResult
from app.modules.users.models import User

pytestmark = pytest.mark.integration


async def create_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    is_superuser: bool = False,
) -> User:
    user = User(
        email=email or f"integration-{uuid.uuid4().hex}@example.com",
        first_name="Integration",
        last_name="Test",
        is_active=True,
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_alembic_upgrades_empty_database(postgres_engine: AsyncEngine) -> None:
    import_models()

    async with postgres_engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )

    assert "alembic_version" in tables
    assert set(Base.metadata.tables).issubset(tables)

    async with postgres_engine.connect() as connection:
        catalog_indexes = await connection.run_sync(
            lambda sync_connection: {
                index["name"]
                for index in inspect(sync_connection).get_indexes("mcp_server_versions")
            }
        )
    assert {
        "ix_mcp_server_versions_search_vector",
        "ix_mcp_server_versions_catalog_source",
        "ix_mcp_server_versions_org_latest_page",
        "ix_mcp_server_versions_org_page",
    }.issubset(catalog_indexes)

    async with postgres_engine.connect() as connection:
        retention_indexes = await connection.run_sync(
            lambda sync_connection: {
                table_name: {
                    index["name"]
                    for index in inspect(sync_connection).get_indexes(table_name)
                }
                for table_name in ("mcp_runtime_events", "mcp_tool_invocations")
            }
        )
    assert "ix_mcp_runtime_events_retention" in retention_indexes["mcp_runtime_events"]
    assert (
        "ix_mcp_tool_invocations_retention"
        in retention_indexes["mcp_tool_invocations"]
    )


@pytest.mark.asyncio
async def test_repository_metadata_rate_limit_is_durable_and_resets(
    postgres_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    now = datetime(2026, 7, 17, tzinfo=UTC)

    async with session_factory() as session:
        user = await create_user(session)
        organization = Organization(
            name="Metadata Rate Limit",
            slug=f"metadata-rate-limit-{uuid.uuid4().hex}",
            status="active",
            created_by_id=user.id,
        )
        session.add(organization)
        await session.commit()

        results = []
        for _ in range(3):
            results.append(
                await consume_repository_metadata_rate_limit(
                    session,
                    organization.id,
                    limit=2,
                    window_seconds=60,
                    now=now,
                )
            )
            await session.commit()

        reset_result = await consume_repository_metadata_rate_limit(
            session,
            organization.id,
            limit=2,
            window_seconds=60,
            now=now + timedelta(seconds=61),
        )

    assert [result.allowed for result in results] == [True, True, False]
    assert reset_result.allowed is True


@pytest.mark.asyncio
async def test_catalog_full_text_search_keyset_and_normalized_source_lookup(
    postgres_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            user = await create_user(session)
            organization = Organization(
                name="Catalog scaling organization",
                slug=f"catalog-scaling-{uuid.uuid4().hex}",
                status="active",
                created_by_id=user.id,
            )
            session.add(organization)
            await session.flush()
            source = MCPCatalogSource(
                organization_id=organization.id,
                name="Scaling source",
                provider="custom",
                base_url=f"https://catalog-{uuid.uuid4().hex}.example.com",
                tenant_id="",
                sync_mode="all_versions",
                is_enabled=True,
                last_error="",
            )
            session.add(source)
            await session.flush()
            now = datetime.now(UTC)
            for name in ("example/forecast", "example/weather"):
                session.add(
                    MCPServerVersion(
                        organization_id=organization.id,
                        catalog_source_id=source.id,
                        name=name,
                        title="Weather forecast tools",
                        description="Accurate weather forecasts and alerts",
                        version="1.0.0",
                        website_url="",
                        status="active",
                        status_message="",
                        is_latest=True,
                        repository=None,
                        packages=[],
                        remotes=[],
                        icons=[],
                        server_json={
                            "$schema": "https://example.com/schema.json",
                            "name": name,
                            "description": "Accurate weather forecasts and alerts",
                            "version": "1.0.0",
                        },
                        published_at=now,
                        status_changed_at=now,
                    )
                )
        organization_id = organization.id
        source_id = source.id

        first_page, next_cursor = await mcp_registry_repository.list_servers(
            session,
            cursor=None,
            limit=1,
            include_deleted=False,
            search="weather forecasts",
            organization_id=organization_id,
        )
        second_page, final_cursor = await mcp_registry_repository.list_servers(
            session,
            cursor=next_cursor,
            limit=1,
            include_deleted=False,
            search="weather forecasts",
            organization_id=organization_id,
        )
        sourced = await mcp_registry_repository.list_server_versions_for_catalog_source(
            session,
            organization_id=organization_id,
            source_id=source_id,
        )

    assert [row.name for row in first_page] == ["example/forecast"]
    assert next_cursor
    assert [row.name for row in second_page] == ["example/weather"]
    assert final_cursor == ""
    assert {row.name for row in sourced} == {"example/forecast", "example/weather"}


@pytest.mark.asyncio
async def test_runtime_retention_deletes_only_one_expired_batch(
    postgres_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    expired_at = cutoff - timedelta(days=1)
    async with session_factory() as session:
        async with session.begin():
            user = await create_user(session)
            organization = Organization(
                name="Runtime retention organization",
                slug=f"runtime-retention-{uuid.uuid4().hex}",
                status="active",
                created_by_id=user.id,
            )
            session.add(organization)
            await session.flush()
            workspace = Workspace(
                organization_id=organization.id,
                name="Runtime retention workspace",
                slug=f"runtime-retention-{uuid.uuid4().hex}",
                description="",
                status="active",
                created_by_id=user.id,
            )
            session.add(workspace)
            await session.flush()
            installation = MCPServerInstallation(
                workspace_id=workspace.id,
                server_name="example/retention",
                config_name="default",
                installed_version="1.0.0",
                status="enabled",
                install_type="metadata",
                install_path="",
                runtime_config={},
                secret_references={},
                install_error="",
                installed_at=now,
            )
            session.add(installation)
            await session.flush()
            runtime_session = MCPRuntimeSession(
                organization_id=organization.id,
                workspace_id=workspace.id,
                installation_id=installation.id,
                server_name=installation.server_name,
                server_version=installation.installed_version,
                runtime_provider="local",
                runtime_kind="process",
                config_fingerprint="retention-test",
                status="stopped",
                pod_name="",
                namespace="",
                endpoint_url="",
                started_at=expired_at,
                ready_at=expired_at,
                last_used_at=expired_at,
                expires_at=None,
                stopped_at=expired_at,
                failure_count=0,
                last_error="",
            )
            session.add(runtime_session)
            await session.flush()
            for created_at in (expired_at, expired_at, expired_at, now):
                session.add(
                    MCPRuntimeEvent(
                        runtime_session_id=runtime_session.id,
                        event_type="retention_test",
                        message="",
                        event_metadata={},
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.add(
                    MCPToolInvocation(
                        organization_id=organization.id,
                        workspace_id=workspace.id,
                        runtime_session_id=runtime_session.id,
                        user_id=user.id,
                        agent_id=None,
                        agent_run_id=None,
                        installation_id=installation.id,
                        server_name=installation.server_name,
                        server_version=installation.installed_version,
                        tool_name="retention_test",
                        status="succeeded",
                        started_at=created_at,
                        finished_at=created_at,
                        duration_ms=1,
                        input_size_bytes=0,
                        output_size_bytes=0,
                        is_error=False,
                        error="",
                    )
                )

        async with session.begin():
            deleted_events = await mcp_runtime_repository.delete_runtime_events_before(
                session,
                cutoff=cutoff,
                limit=2,
            )
            deleted_invocations = (
                await mcp_runtime_repository.delete_tool_invocations_before(
                    session,
                    cutoff=cutoff,
                    limit=2,
                )
            )

        expired_event_count = await session.scalar(
            select(func.count())
            .select_from(MCPRuntimeEvent)
            .where(MCPRuntimeEvent.created_at < cutoff)
        )
        expired_invocation_count = await session.scalar(
            select(func.count())
            .select_from(MCPToolInvocation)
            .where(MCPToolInvocation.started_at < cutoff)
        )
        event_count = await session.scalar(
            select(func.count()).select_from(MCPRuntimeEvent)
        )
        invocation_count = await session.scalar(
            select(func.count()).select_from(MCPToolInvocation)
        )

    assert deleted_events == 2
    assert deleted_invocations == 2
    assert expired_event_count == 1
    assert expired_invocation_count == 1
    assert event_count == 2
    assert invocation_count == 2


@pytest.mark.asyncio
async def test_database_enforces_check_and_partial_unique_constraints(
    postgres_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            user = await create_user(session)
        user_id = user.id

        session.add(
            Organization(
                name="Invalid status",
                slug=f"invalid-{uuid.uuid4().hex}",
                status="invalid",
                created_by_id=user_id,
            )
        )
        with pytest.raises(IntegrityError, match="ck_organizations_status"):
            await session.commit()
        await session.rollback()

        async with session.begin():
            organization = Organization(
                name="Constraint organization",
                slug=f"constraints-{uuid.uuid4().hex}",
                status="active",
                created_by_id=user_id,
            )
            session.add(organization)
        organization_id = organization.id

        async with session.begin():
            session.add(
                SecretStore(
                    organization_id=organization_id,
                    workspace_id=None,
                    created_by_id=user_id,
                    provider="openbao",
                    name="shared-store",
                    config={"baseUrl": "https://vault-one.example"},
                    auth_config={},
                    is_active=True,
                )
            )

        session.add(
            SecretStore(
                organization_id=organization_id,
                workspace_id=None,
                created_by_id=user_id,
                provider="openbao",
                name="shared-store",
                config={"baseUrl": "https://vault-two.example"},
                auth_config={},
                is_active=True,
            )
        )
        with pytest.raises(IntegrityError, match="uq_secret_stores_org_name"):
            await session.commit()


@pytest.mark.asyncio
async def test_deleting_credential_secret_handle_or_store_returns_typed_conflict(
    postgres_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            user = await create_user(session, is_superuser=True)
            organization = Organization(
                name="Secret constraint organization",
                slug=f"secret-constraint-{uuid.uuid4().hex}",
                status="active",
                created_by_id=user.id,
            )
            session.add(organization)
            await session.flush()
            store = SecretStore(
                organization_id=organization.id,
                workspace_id=None,
                created_by_id=user.id,
                provider="openbao",
                name="Credential store",
                config={"baseUrl": "https://vault-credential.example"},
                auth_config={},
                is_active=True,
            )
            session.add(store)
            await session.flush()
            handle = SecretHandle(
                organization_id=organization.id,
                workspace_id=None,
                store_id=store.id,
                created_by_id=user.id,
                purpose="llm_credential",
                display_name="Credential API key",
                external_ref="wardn/integration/credential",
                key_name="api_key",
                version="",
                handle_metadata={},
            )
            session.add(handle)
            await session.flush()
            session.add(
                LLMProviderCredential(
                    organization_id=organization.id,
                    workspace_id=None,
                    user_id=None,
                    name="Restricted credential",
                    provider="openai_api_key",
                    visibility="organization",
                    auth_method="api_key",
                    api_key_secret_handle_id=handle.id,
                    oauth_provider="",
                    oauth_scopes=[],
                    oauth_metadata={},
                    base_url="",
                    extra_headers={},
                    is_active=True,
                )
            )

        user_id = user.id
        organization_id = organization.id
        store_id = store.id
        handle_id = handle.id

        with pytest.raises(SecretInUseError, match="handle is used"):
            async with session.begin():
                current_user = await session.get(User, user_id)
                assert current_user is not None
                await secrets_service.delete_secret_handle(
                    session,
                    current_user,
                    organization_id,
                    handle_id,
                )

        with pytest.raises(SecretInUseError, match="store contains a handle"):
            async with session.begin():
                current_user = await session.get(User, user_id)
                assert current_user is not None
                await secrets_service.delete_secret_store(
                    session,
                    current_user,
                    organization_id,
                    store_id,
                )

    async with session_factory() as verification_session:
        assert await verification_session.get(SecretHandle, handle_id) is not None
        assert await verification_session.get(SecretStore, store_id) is not None


@pytest.mark.asyncio
async def test_external_secret_write_rollback_leaves_durable_cleanup_intent(
    postgres_engine: AsyncEngine,
    monkeypatch,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    writes: list[str] = []

    async with session_factory() as session:
        async with session.begin():
            user = await create_user(session, is_superuser=True)
            organization = Organization(
                name="Managed secret organization",
                slug=f"managed-secret-{uuid.uuid4().hex}",
                status="active",
                created_by_id=user.id,
            )
            session.add(organization)
            await session.flush()
            store = SecretStore(
                organization_id=organization.id,
                workspace_id=None,
                created_by_id=user.id,
                provider="openbao",
                name="Managed secret store",
                config={"baseUrl": "https://vault-managed.example"},
                auth_config={},
                is_active=True,
            )
            session.add(store)
        user_id = user.id
        organization_id = organization.id
        store_id = store.id

    original_persist = managed_secrets_service.persist_managed_secret_intent

    async def persist_intent(**kwargs):
        return await original_persist(**kwargs, session_factory=session_factory)

    class Provider:
        async def write(self, store, external_ref, values, context):
            writes.append(external_ref)
            return SecretWriteResult(version="1")

    monkeypatch.setattr(secrets_service, "persist_managed_secret_intent", persist_intent)
    monkeypatch.setattr(secrets_service, "get_secret_provider", lambda _name: Provider())

    async with session_factory() as request_session:
        current_user = await request_session.get(User, user_id)
        assert current_user is not None
        result = await secrets_service.write_secret_values(
            request_session,
            current_user,
            organization_id,
            store_id,
            workspace_id=None,
            external_ref="wardn/integration/rolled-back",
            values={"api_key": "secret"},
            purpose="llm_credential",
            owner_type="llm_provider_credential",
            owner_id=uuid.uuid4(),
        )
        assert result.managed_secret_id is not None
        managed_secret_id = result.managed_secret_id
        await request_session.rollback()
        await run_deferred_session_work(request_session)

    assert writes == ["wardn/integration/rolled-back"]
    async with session_factory() as verification_session:
        managed_secret = await verification_session.get(ManagedSecret, managed_secret_id)
        assert managed_secret is not None
        assert managed_secret.status == "cleanup_pending"
        assert managed_secret.external_ref == "wardn/integration/rolled-back"

        current_user = await verification_session.get(User, user_id)
        assert current_user is not None
        with pytest.raises(SecretInUseError):
            await secrets_service.delete_secret_store(
                verification_session,
                current_user,
                organization_id,
                store_id,
            )


@pytest.mark.asyncio
async def test_transaction_rollback_discards_changes(postgres_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    user_id: uuid.UUID

    async with session_factory() as session:
        transaction = await session.begin()
        user = await create_user(session)
        user_id = user.id
        await transaction.rollback()

    async with session_factory() as session:
        assert await session.get(User, user_id) is None


@pytest.mark.asyncio
async def test_concurrent_duplicate_organization_is_typed_conflict(
    postgres_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        user = await create_user(session)
        user_id = user.id

    slug = f"concurrent-{uuid.uuid4().hex}"
    payload = OrganizationCreate(name="Concurrent organization", slug=slug)

    async def create_once():
        async with session_factory() as session:
            try:
                async with session.begin():
                    current_user = await session.get(User, user_id)
                    assert current_user is not None
                    return await organization_service.create_organization(
                        session,
                        current_user,
                        payload,
                    )
            except DuplicateOrganizationError as exc:
                return exc

    results = await asyncio.gather(create_once(), create_once())

    assert sum(isinstance(result, DuplicateOrganizationError) for result in results) == 1
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Organization).where(Organization.slug == slug)
        )
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_workspace_quota_is_atomic(postgres_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        user = await create_user(session)
        organization = await organization_service.create_organization(
            session,
            user,
            OrganizationCreate(
                name="Quota organization",
                slug=f"quota-{uuid.uuid4().hex}",
            ),
        )
        session.add(
            ResourceLimit(
                scope_type="organization",
                scope_id=organization.id,
                limit_key=WORKSPACES_PER_ORGANIZATION,
                value=1,
            )
        )
        user_id = user.id
        organization_id = organization.id

    async def create_workspace_once(index: int):
        async with session_factory() as session:
            try:
                async with session.begin():
                    current_user = await session.get(User, user_id)
                    assert current_user is not None
                    return await organization_service.create_workspace(
                        session,
                        current_user,
                        organization_id,
                        WorkspaceCreate(
                            name=f"Concurrent workspace {index}",
                            slug=f"concurrent-workspace-{index}-{uuid.uuid4().hex}",
                        ),
                    )
            except LimitExceededError as exc:
                return exc

    results = await asyncio.gather(create_workspace_once(1), create_workspace_once(2))

    assert sum(isinstance(result, LimitExceededError) for result in results) == 1
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.organization_id == organization_id)
        )
    assert count == 1


@pytest.mark.asyncio
async def test_repository_queries_and_database_cascades(postgres_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        user = await create_user(session)
        organization = await organization_service.create_organization(
            session,
            user,
            OrganizationCreate(
                name="Cascade organization",
                slug=f"cascade-{uuid.uuid4().hex}",
            ),
        )
        workspace = await organization_service.create_workspace(
            session,
            user,
            organization.id,
            WorkspaceCreate(name="Cascade workspace", slug="cascade-workspace"),
        )
        user_id = user.id
        organization_id = organization.id
        workspace_id = workspace.id

    async with session_factory.begin() as session:
        rows = await organization_repository.list_workspaces_for_user(
            session,
            organization_id,
            user_id,
        )
        assert [(row.id, membership.role) for row, membership in rows if membership] == [
            (workspace_id, "owner")
        ]
        await session.execute(delete(Organization).where(Organization.id == organization_id))

    async with session_factory() as session:
        assert await session.get(Workspace, workspace_id) is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(OrganizationMembership.organization_id == organization_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace_id)
            )
            == 0
        )
