import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits import service as limits_service
from app.modules.organizations import repository
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    DuplicateWorkspaceError,
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.schemas import (
    OrganizationCreate,
    OrganizationListResponse,
    OrganizationRead,
    OrganizationUpdate,
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.modules.users.models import User

ORG_ADMIN_ROLES = {"owner", "admin"}
WORKSPACE_ADMIN_ROLES = {"owner", "admin"}


def normalize_slug(value: str) -> str:
    return value.strip().casefold()


def organization_role_for_user(
    user: User,
    membership: OrganizationMembership | None,
) -> str:
    if user.is_superuser:
        return "owner"
    return membership.role if membership else ""


def workspace_role_for_user(
    user: User,
    organization_membership: OrganizationMembership | None,
    workspace_membership: WorkspaceMembership | None,
) -> str:
    if user.is_superuser:
        return "owner"
    if organization_membership and organization_membership.role in ORG_ADMIN_ROLES:
        return "admin"
    return workspace_membership.role if workspace_membership else ""


def organization_response(
    organization: Organization,
    *,
    role: str,
) -> OrganizationRead:
    return OrganizationRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        status=organization.status,
        currentUserRole=role,
        createdAt=organization.created_at,
        updatedAt=organization.updated_at,
    )


def workspace_response(
    workspace: Workspace,
    *,
    role: str,
) -> WorkspaceRead:
    return WorkspaceRead(
        id=workspace.id,
        organizationId=workspace.organization_id,
        name=workspace.name,
        slug=workspace.slug,
        description=workspace.description,
        status=workspace.status,
        currentUserRole=role,
        createdAt=workspace.created_at,
        updatedAt=workspace.updated_at,
    )


async def list_organizations(
    session: AsyncSession,
    user: User,
) -> OrganizationListResponse:
    if user.is_superuser:
        rows = await repository.list_organizations_for_user(session, user.id)
    else:
        rows = await repository.list_joined_organizations_for_user(session, user.id)
    return OrganizationListResponse(
        organizations=[
            organization_response(
                organization,
                role=organization_role_for_user(user, membership),
            )
            for organization, membership in rows
        ]
    )


async def require_organization_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> tuple[Organization, OrganizationMembership | None]:
    organization = await repository.get_organization_by_id(session, organization_id)
    if organization is None or organization.status == "archived":
        raise OrganizationNotFoundError("organization not found")
    membership = await repository.get_organization_membership(
        session,
        organization_id,
        user.id,
    )
    if not user.is_superuser and membership is None:
        raise OrganizationAccessDeniedError("organization access denied")
    return organization, membership


async def require_organization_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> tuple[Organization, OrganizationMembership | None]:
    organization, membership = await require_organization_member(session, user, organization_id)
    if organization.status != "active":
        raise OrganizationAccessDeniedError("organization is not active")
    if not user.is_superuser and (membership is None or membership.role not in ORG_ADMIN_ROLES):
        raise OrganizationAccessDeniedError("organization admin access required")
    return organization, membership


async def create_organization(
    session: AsyncSession,
    user: User,
    payload: OrganizationCreate,
) -> OrganizationRead:
    if not user.is_superuser:
        raise OrganizationAccessDeniedError("only superusers can create organizations")
    slug = normalize_slug(payload.slug)
    if await repository.get_organization_by_slug(session, slug):
        raise DuplicateOrganizationError("organization slug already exists")

    organization = Organization(
        name=payload.name.strip(),
        slug=slug,
        status="active",
        created_by_id=user.id,
    )
    session.add(organization)
    await session.flush()
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )
    session.add(membership)
    await session.flush()
    await session.refresh(organization)
    return organization_response(organization, role="owner")


async def get_organization(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> OrganizationRead:
    organization, membership = await require_organization_member(session, user, organization_id)
    return organization_response(
        organization,
        role=organization_role_for_user(user, membership),
    )


async def update_organization(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
) -> OrganizationRead:
    organization, membership = await require_organization_admin(session, user, organization_id)
    organization.name = payload.name.strip()
    organization.status = payload.status
    await session.flush()
    await session.refresh(organization)
    return organization_response(
        organization,
        role=organization_role_for_user(user, membership),
    )


async def require_workspace_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[Workspace, OrganizationMembership | None, WorkspaceMembership | None]:
    organization, organization_membership = await require_organization_member(
        session,
        user,
        organization_id,
    )
    workspace = await repository.get_workspace_by_id(session, workspace_id)
    if (
        workspace is None
        or workspace.organization_id != organization.id
        or workspace.status == "archived"
    ):
        raise WorkspaceNotFoundError("workspace not found")

    workspace_membership = await repository.get_workspace_membership(
        session,
        workspace.id,
        user.id,
    )
    if (
        not user.is_superuser
        and not (
            organization_membership
            and organization_membership.role in ORG_ADMIN_ROLES
        )
        and workspace_membership is None
    ):
        raise WorkspaceAccessDeniedError("workspace access denied")
    return workspace, organization_membership, workspace_membership


async def require_workspace_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[Workspace, OrganizationMembership | None, WorkspaceMembership | None]:
    workspace, organization_membership, workspace_membership = await require_workspace_member(
        session,
        user,
        organization_id,
        workspace_id,
    )
    if workspace.status != "active":
        raise WorkspaceAccessDeniedError("workspace is not active")
    role = workspace_role_for_user(user, organization_membership, workspace_membership)
    if role not in WORKSPACE_ADMIN_ROLES:
        raise WorkspaceAccessDeniedError("workspace admin access required")
    return workspace, organization_membership, workspace_membership


async def list_workspaces(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> WorkspaceListResponse:
    _organization, organization_membership = await require_organization_member(
        session,
        user,
        organization_id,
    )
    rows = await repository.list_workspaces_for_user(
        session,
        organization_id,
        user.id,
    )
    return WorkspaceListResponse(
        workspaces=[
            workspace_response(
                workspace,
                role=workspace_role_for_user(user, organization_membership, membership),
            )
            for workspace, membership in rows
            if user.is_superuser
            or (organization_membership and organization_membership.role in ORG_ADMIN_ROLES)
            or membership is not None
        ]
    )


async def create_workspace(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: WorkspaceCreate,
) -> WorkspaceRead:
    _organization, organization_membership = await require_organization_admin(
        session,
        user,
        organization_id,
    )
    slug = normalize_slug(payload.slug)
    if await repository.get_workspace_by_slug(session, organization_id, slug):
        raise DuplicateWorkspaceError("workspace slug already exists")

    organization_workspace_count = await repository.count_active_workspaces_for_organization(
        session,
        organization_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.WORKSPACES_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=organization_workspace_count,
    )

    user_workspace_count = (
        await repository.count_active_workspaces_created_by_user_for_organization(
            session,
            organization_id=organization_id,
            user_id=user.id,
        )
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.WORKSPACES_CREATED_PER_USER,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=user_workspace_count,
    )

    workspace = Workspace(
        organization_id=organization_id,
        name=payload.name.strip(),
        slug=slug,
        description=payload.description.strip(),
        status="active",
        created_by_id=user.id,
    )
    session.add(workspace)
    await session.flush()
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )
    session.add(membership)
    await session.flush()
    await session.refresh(workspace)
    return workspace_response(
        workspace,
        role=workspace_role_for_user(user, organization_membership, membership),
    )


async def get_workspace(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> WorkspaceRead:
    workspace, organization_membership, workspace_membership = await require_workspace_member(
        session,
        user,
        organization_id,
        workspace_id,
    )
    return workspace_response(
        workspace,
        role=workspace_role_for_user(user, organization_membership, workspace_membership),
    )


async def update_workspace(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
) -> WorkspaceRead:
    workspace, organization_membership, workspace_membership = await require_workspace_admin(
        session,
        user,
        organization_id,
        workspace_id,
    )
    workspace.name = payload.name.strip()
    workspace.description = payload.description.strip()
    workspace.status = payload.status
    await session.flush()
    await session.refresh(workspace)
    return workspace_response(
        workspace,
        role=workspace_role_for_user(user, organization_membership, workspace_membership),
    )
