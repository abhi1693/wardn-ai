from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.limits.exceptions import LimitExceededError
from app.modules.organizations import service
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    OrganizationAccessDeniedError,
    WorkspaceAccessDeniedError,
    WorkspaceDeletionBlockedError,
)
from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.schemas import OrganizationCreate, WorkspaceCreate
from app.modules.users.models import User
from tests.database_fakes import EmptyResult


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = False
        self.flush_count = 0
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True
        self.flush_count += 1
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 21, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        instance.created_at = now
        instance.updated_at = now
        self.refreshed.append(instance)

    async def execute(self, *args, **kwargs) -> EmptyResult:
        return EmptyResult()

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)


class ConstraintFailureSession(FakeSession):
    def __init__(self, constraint_name: str) -> None:
        super().__init__()
        self.constraint_name = constraint_name

    async def flush(self) -> None:
        raise IntegrityError("insert", {}, Exception(self.constraint_name))


@pytest.mark.asyncio
async def test_superuser_can_create_organization(monkeypatch) -> None:
    async def missing_organization(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_slug", missing_organization)
    user = User(id=uuid4(), email="admin@example.com", is_superuser=True)
    session = FakeSession()

    response = await service.create_organization(
        session,
        user,
        OrganizationCreate(name=" Platform Team ", slug="platform"),
    )

    organization, membership = session.added
    assert response.name == "Platform Team"
    assert response.slug == "platform"
    assert response.current_user_role == "owner"
    assert isinstance(organization, Organization)
    assert isinstance(membership, OrganizationMembership)
    assert membership.organization_id == organization.id
    assert membership.user_id == user.id
    assert membership.role == "owner"


@pytest.mark.asyncio
async def test_regular_user_can_create_and_own_organization(monkeypatch) -> None:
    async def missing_organization(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_slug", missing_organization)
    user = User(id=uuid4(), email="user@example.com", is_superuser=False)
    session = FakeSession()

    response = await service.create_organization(
        session,
        user,
        OrganizationCreate(name=" Personal Team ", slug="personal"),
    )

    organization, membership = session.added
    assert response.name == "Personal Team"
    assert response.slug == "personal"
    assert response.current_user_role == "owner"
    assert isinstance(organization, Organization)
    assert isinstance(membership, OrganizationMembership)
    assert organization.created_by_id == user.id
    assert membership.organization_id == organization.id
    assert membership.user_id == user.id
    assert membership.role == "owner"
    assert membership.is_active is True


@pytest.mark.asyncio
async def test_create_organization_translates_slug_constraint_race(monkeypatch) -> None:
    async def missing_organization(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_slug", missing_organization)
    user = User(id=uuid4(), email="admin@example.com", is_superuser=True)

    with pytest.raises(DuplicateOrganizationError, match="slug already exists"):
        await service.create_organization(
            ConstraintFailureSession("uq_organizations_slug"),
            user,
            OrganizationCreate(name="Platform", slug="platform"),
        )


@pytest.mark.asyncio
async def test_create_organization_preserves_unrelated_integrity_error(monkeypatch) -> None:
    async def missing_organization(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_slug", missing_organization)
    user = User(id=uuid4(), email="admin@example.com", is_superuser=True)

    with pytest.raises(IntegrityError):
        await service.create_organization(
            ConstraintFailureSession("fk_organizations_created_by_id"),
            user,
            OrganizationCreate(name="Platform", slug="platform"),
        )


@pytest.mark.asyncio
async def test_regular_user_cannot_access_unjoined_organization(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="outsider@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Personal Team",
        slug="personal",
        status="active",
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(
        service.repository,
        "get_organization_membership",
        get_organization_membership,
    )

    with pytest.raises(OrganizationAccessDeniedError):
        await service.get_organization(FakeSession(), user, organization_id)


@pytest.mark.asyncio
async def test_organization_admin_can_create_workspace(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Default Organization",
        slug="default",
        status="active",
    )
    organization_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return organization_membership

    async def get_workspace_by_slug(*args, **kwargs):
        return None

    async def count_active_workspaces_for_organization(*args, **kwargs):
        return 0

    async def count_active_workspaces_created_by_user(*args, **kwargs):
        return 0

    async def require_limit_available(*args, **kwargs):
        return None

    default_limit_workspaces = []

    async def ensure_default_workspace_resource_limits(*args, **kwargs):
        default_limit_workspaces.append(args[1])

    monkeypatch.setattr(service.repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(
        service.repository,
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(service.repository, "get_workspace_by_slug", get_workspace_by_slug)
    monkeypatch.setattr(
        service.repository,
        "count_active_workspaces_for_organization",
        count_active_workspaces_for_organization,
    )
    monkeypatch.setattr(
        service.repository,
        "count_active_workspaces_created_by_user",
        count_active_workspaces_created_by_user,
    )
    monkeypatch.setattr(
        service.limits_service,
        "require_limit_available",
        require_limit_available,
    )
    monkeypatch.setattr(
        service.limits_service,
        "ensure_default_workspace_resource_limits",
        ensure_default_workspace_resource_limits,
    )
    session = FakeSession()

    response = await service.create_workspace(
        session,
        user,
        organization_id,
        WorkspaceCreate(name=" Production ", slug="prod", description=" Primary runtime "),
    )

    workspace, membership = session.added
    assert response.name == "Production"
    assert response.slug == "prod"
    assert response.description == "Primary runtime"
    assert response.current_user_role == "admin"
    assert isinstance(workspace, Workspace)
    assert isinstance(membership, WorkspaceMembership)
    assert workspace.organization_id == organization_id
    assert membership.workspace_id == workspace.id
    assert membership.role == "owner"
    assert default_limit_workspaces == [workspace.id]


@pytest.mark.asyncio
async def test_create_workspace_enforces_user_created_workspace_limit(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Default Organization",
        slug="default",
        status="active",
    )
    organization_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return organization_membership

    async def get_workspace_by_slug(*args, **kwargs):
        return None

    async def count_active_workspaces_for_organization(*args, **kwargs):
        return 0

    async def count_active_workspaces_created_by_user(*args, **kwargs):
        return 3

    async def require_limit_available(*args, **kwargs):
        if kwargs["limit_key"] == service.limits_service.WORKSPACES_CREATED_PER_USER:
            raise LimitExceededError("workspaces.created_per_user limit exceeded: 3/3")

    monkeypatch.setattr(service.repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(
        service.repository,
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(service.repository, "get_workspace_by_slug", get_workspace_by_slug)
    monkeypatch.setattr(
        service.repository,
        "count_active_workspaces_for_organization",
        count_active_workspaces_for_organization,
    )
    monkeypatch.setattr(
        service.repository,
        "count_active_workspaces_created_by_user",
        count_active_workspaces_created_by_user,
    )
    monkeypatch.setattr(
        service.limits_service,
        "require_limit_available",
        require_limit_available,
    )

    with pytest.raises(LimitExceededError):
        await service.create_workspace(
            FakeSession(),
            user,
            organization_id,
            WorkspaceCreate(name="Production", slug="prod", description="Primary runtime"),
        )


@pytest.mark.asyncio
async def test_workspace_member_is_not_workspace_admin(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    organization = Organization(
        id=organization_id,
        name="Default Organization",
        slug="default",
        status="active",
    )
    organization_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default Workspace",
        slug="default",
        status="active",
    )
    workspace_membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return organization_membership

    async def get_workspace_by_id(*args, **kwargs):
        return workspace

    async def get_workspace_membership(*args, **kwargs):
        return workspace_membership

    monkeypatch.setattr(service.repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(
        service.repository,
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(service.repository, "get_workspace_by_id", get_workspace_by_id)
    monkeypatch.setattr(service.repository, "get_workspace_membership", get_workspace_membership)

    with pytest.raises(WorkspaceAccessDeniedError):
        await service.require_workspace_admin(
            FakeSession(),
            user,
            organization_id,
            workspace_id,
        )


@pytest.mark.asyncio
async def test_workspace_admin_can_delete_empty_workspace(monkeypatch) -> None:
    organization_id = uuid4()
    workspace = Workspace(
        id=uuid4(),
        organization_id=organization_id,
        name="Temporary",
        slug="temporary",
        status="active",
    )
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    async def require_workspace_admin(*args, **kwargs):
        return workspace, None, None

    async def no_default_workspace(*args, **kwargs):
        return None

    async def no_dependencies(*args, **kwargs):
        return 0

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_default_workspace", no_default_workspace)
    monkeypatch.setattr(
        service.mcp_registry_repository,
        "count_installations_for_workspace",
        no_dependencies,
    )
    monkeypatch.setattr(
        service.managed_secrets_repository,
        "count_managed_secrets_for_workspace",
        no_dependencies,
    )
    session = FakeSession()

    await service.delete_workspace(session, user, organization_id, workspace.id)

    assert session.deleted == [workspace]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_default_workspace_requires_replacement_before_deletion(monkeypatch) -> None:
    organization_id = uuid4()
    workspace = Workspace(
        id=uuid4(),
        organization_id=organization_id,
        name="Default Workspace",
        slug="default",
        status="active",
    )
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    async def require_workspace_admin(*args, **kwargs):
        return workspace, None, None

    async def default_workspace(*args, **kwargs):
        return workspace

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_default_workspace", default_workspace)

    with pytest.raises(WorkspaceDeletionBlockedError, match="select an active replacement"):
        await service.delete_workspace(FakeSession(), user, organization_id, workspace.id)


@pytest.mark.asyncio
async def test_default_workspace_promotes_replacement_before_deletion(monkeypatch) -> None:
    organization_id = uuid4()
    default_workspace = Workspace(
        id=uuid4(),
        organization_id=organization_id,
        name="Default Workspace",
        slug="default",
        status="active",
    )
    replacement_workspace = Workspace(
        id=uuid4(),
        organization_id=organization_id,
        name="Replacement",
        slug="replacement",
        status="active",
    )
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    async def require_workspace_admin(*args, **kwargs):
        requested_id = args[3]
        if requested_id == default_workspace.id:
            return default_workspace, None, None
        if requested_id == replacement_workspace.id:
            return replacement_workspace, None, None
        raise AssertionError(f"unexpected workspace ID: {requested_id}")

    async def get_default_workspace(*args, **kwargs):
        return default_workspace

    async def no_dependencies(*args, **kwargs):
        return 0

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_default_workspace", get_default_workspace)
    monkeypatch.setattr(
        service.mcp_registry_repository,
        "count_installations_for_workspace",
        no_dependencies,
    )
    monkeypatch.setattr(
        service.managed_secrets_repository,
        "count_managed_secrets_for_workspace",
        no_dependencies,
    )
    session = FakeSession()

    await service.delete_workspace(
        session,
        user,
        organization_id,
        default_workspace.id,
        replacement_workspace_id=replacement_workspace.id,
    )

    assert default_workspace.slug == f"deleting-{default_workspace.id.hex}"
    assert replacement_workspace.slug == "default"
    assert session.deleted == [default_workspace]
    assert session.flush_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("installation_count", "managed_secret_count", "message"),
    [
        (1, 0, "uninstall all MCP server configurations"),
        (0, 1, "remove connections that own managed secrets"),
    ],
)
async def test_workspace_dependencies_block_deletion(
    monkeypatch,
    installation_count: int,
    managed_secret_count: int,
    message: str,
) -> None:
    organization_id = uuid4()
    workspace = Workspace(
        id=uuid4(),
        organization_id=organization_id,
        name="Production",
        slug="production",
        status="active",
    )
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    async def require_workspace_admin(*args, **kwargs):
        return workspace, None, None

    async def no_default_workspace(*args, **kwargs):
        return None

    async def count_installations(*args, **kwargs):
        return installation_count

    async def count_managed_secrets(*args, **kwargs):
        return managed_secret_count

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_default_workspace", no_default_workspace)
    monkeypatch.setattr(
        service.mcp_registry_repository,
        "count_installations_for_workspace",
        count_installations,
    )
    monkeypatch.setattr(
        service.managed_secrets_repository,
        "count_managed_secrets_for_workspace",
        count_managed_secrets,
    )

    with pytest.raises(WorkspaceDeletionBlockedError, match=message):
        await service.delete_workspace(FakeSession(), user, organization_id, workspace.id)
