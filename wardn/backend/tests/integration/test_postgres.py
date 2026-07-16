import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.base import Base, import_models
from app.modules.limits.exceptions import LimitExceededError
from app.modules.limits.models import ResourceLimit
from app.modules.limits.service import WORKSPACES_PER_ORGANIZATION
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
from app.modules.secrets.models import SecretStore
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
