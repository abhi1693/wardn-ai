import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
from app.modules.limits import service as limits_service
from app.modules.mcp_registry import repository as mcp_registry_repository
from app.modules.organizations import repository
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    DuplicateWorkspaceError,
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceDeletionBlockedError,
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
from app.modules.secrets import managed_repository as managed_secrets_repository
from app.modules.users.models import User

logger = logging.getLogger(__name__)

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
        guardrailDefaultDeny=bool(workspace.guardrail_default_deny),
        currentUserRole=role,
        createdAt=workspace.created_at,
        updatedAt=workspace.updated_at,
    )


def organization_log_extra(
    *,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, str | None]:
    return {
        "organization_id": str(organization_id) if organization_id else None,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "user_id": str(user_id) if user_id else None,
    }


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
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, {"uq_organizations_slug"}):
            raise DuplicateOrganizationError("organization slug already exists") from exc
        raise
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )
    session.add(membership)
    await session.flush()
    await session.refresh(organization)
    logger.info(
        "Created organization.",
        extra=organization_log_extra(
            organization_id=organization.id,
            user_id=user.id,
        ),
    )
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
    logger.info(
        "Updated organization.",
        extra={
            **organization_log_extra(
                organization_id=organization.id,
                user_id=user.id,
            ),
            "organization_status": organization.status,
        },
    )
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

    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.WORKSPACES_PER_ORGANIZATION,
                organization_id,
            ),
            limits_service.quota_scope(
                limits_service.WORKSPACES_CREATED_PER_USER,
                organization_id,
                user.id,
            ),
        ],
    )
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
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, {"uq_workspaces_org_slug"}):
            raise DuplicateWorkspaceError("workspace slug already exists") from exc
        raise
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )
    session.add(membership)
    await limits_service.ensure_default_workspace_resource_limits(session, workspace.id)
    await session.flush()
    await session.refresh(workspace)
    logger.info(
        "Created workspace.",
        extra=organization_log_extra(
            organization_id=organization_id,
            workspace_id=workspace.id,
            user_id=user.id,
        ),
    )
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
    if payload.guardrail_default_deny is not None:
        workspace.guardrail_default_deny = payload.guardrail_default_deny
    await session.flush()
    await session.refresh(workspace)
    logger.info(
        "Updated workspace.",
        extra={
            **organization_log_extra(
                organization_id=organization_id,
                workspace_id=workspace.id,
                user_id=user.id,
            ),
            "workspace_status": workspace.status,
        },
    )
    return workspace_response(
        workspace,
        role=workspace_role_for_user(user, organization_membership, workspace_membership),
    )


async def delete_workspace(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    workspace, _organization_membership, _workspace_membership = await require_workspace_admin(
        session,
        user,
        organization_id,
        workspace_id,
    )
    default_workspace = await repository.get_default_workspace(session)
    if default_workspace is not None and default_workspace.id == workspace.id:
        raise WorkspaceDeletionBlockedError("the protected default workspace cannot be deleted")

    installation_count = await mcp_registry_repository.count_installations_for_workspace(
        session,
        workspace.id,
    )
    if installation_count:
        raise WorkspaceDeletionBlockedError(
            "uninstall all MCP server configurations before deleting this workspace"
        )

    managed_secret_count = await managed_secrets_repository.count_managed_secrets_for_workspace(
        session,
        workspace.id,
    )
    if managed_secret_count:
        raise WorkspaceDeletionBlockedError(
            "remove connections that own managed secrets and wait for secret cleanup "
            "before deleting this workspace"
        )

    await repository.delete_workspace(session, workspace)
    await session.flush()
    logger.info(
        "Deleted workspace.",
        extra=organization_log_extra(
            organization_id=organization_id,
            workspace_id=workspace.id,
            user_id=user.id,
        ),
    )
