from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.limits.exceptions import LimitExceededError
from app.modules.organizations import service
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    WorkspaceAccessDeniedError,
)
from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.schemas import OrganizationCreate, WorkspaceCreate
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True
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
async def test_regular_user_cannot_create_organization() -> None:
    user = User(id=uuid4(), email="user@example.com", is_superuser=False)

    with pytest.raises(OrganizationAccessDeniedError):
        await service.create_organization(
            FakeSession(),
            user,
            OrganizationCreate(name="Platform Team", slug="platform"),
        )


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
