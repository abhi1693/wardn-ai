import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.domain_types import MembershipRole
from app.modules.organizations import repository
from app.modules.organizations.exceptions import (
    DuplicateInvitationError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    MembershipNotFoundError,
    MembershipRoleError,
    OrganizationNotFoundError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.models import (
    MembershipInvitation,
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.schemas import (
    InvitationAcceptanceRead,
    InvitationCreate,
    InvitationCreated,
    InvitationListResponse,
    InvitationPreview,
    InvitationRead,
    InvitationRegistration,
    MemberListResponse,
    MemberRead,
    MembershipRoleUpdate,
    PendingInvitationListResponse,
    PendingInvitationRead,
)
from app.modules.organizations.service import (
    ORG_ADMIN_ROLES,
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users import repository as users_repository
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user, normalize_email

logger = logging.getLogger(__name__)


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def hash_invitation_token(token: str) -> str:
    secret = get_settings().api_token_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, f"membership-invitation:{token}".encode(), hashlib.sha256).hexdigest()


def invitation_status(
    invitation: MembershipInvitation,
    *,
    now: datetime | None = None,
) -> Literal["pending", "accepted", "revoked", "expired"]:
    if invitation.status == "pending" and invitation.expires_at <= (now or datetime.now(UTC)):
        return "expired"
    return cast(Literal["pending", "accepted", "revoked"], invitation.status)


def invitation_response(invitation: MembershipInvitation) -> InvitationRead:
    return InvitationRead(
        id=invitation.id,
        organization_id=invitation.organization_id,
        workspace_id=invitation.workspace_id,
        scope_type=cast(Literal["organization", "workspace"], invitation.scope_type),
        email=invitation.email,
        role=invitation.role,
        status=invitation_status(invitation),
        expires_at=invitation.expires_at,
        invited_by_id=invitation.invited_by_id,
        accepted_by_id=invitation.accepted_by_id,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


def pending_invitation_response(
    invitation: MembershipInvitation,
    organization: Organization,
    workspace: Workspace | None,
) -> PendingInvitationRead:
    return PendingInvitationRead(
        id=invitation.id,
        role=invitation.role,
        scope_type=cast(Literal["organization", "workspace"], invitation.scope_type),
        organization_id=organization.id,
        organization_name=organization.name,
        workspace_id=workspace.id if workspace else None,
        workspace_name=workspace.name if workspace else None,
        expires_at=invitation.expires_at,
    )


def member_response(
    membership: OrganizationMembership | WorkspaceMembership,
    user: User,
    *,
    access_source: str,
    role: str | None = None,
    organization_role: str | None = None,
    editable: bool = True,
) -> MemberRead:
    return MemberRead(
        membership_id=membership.id if editable else None,
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        role=role or membership.role,
        access_source=cast(Literal["organization", "workspace"], access_source),
        organization_role=organization_role,
        created_at=membership.created_at,
    )


def organization_actor_role(user: User, membership: OrganizationMembership | None) -> str:
    if user.is_superuser:
        return "owner"
    return membership.role if membership else ""


def require_organization_owner_action(
    actor_role: str,
    *,
    current_role: str | None = None,
    requested_role: str | None = None,
) -> None:
    if actor_role == "owner":
        return
    if current_role == "owner" or requested_role == "owner":
        raise MembershipRoleError("only organization owners can manage the owner role")


def workspace_actor_role(
    user: User,
    organization_membership: OrganizationMembership | None,
    workspace_membership: WorkspaceMembership | None,
) -> str:
    if user.is_superuser or (
        organization_membership and organization_membership.role in ORG_ADMIN_ROLES
    ):
        return "organization_admin"
    return workspace_membership.role if workspace_membership else ""


def require_workspace_owner_action(
    actor_role: str,
    *,
    current_role: str | None = None,
    requested_role: str | None = None,
) -> None:
    if actor_role in {"organization_admin", "owner"}:
        return
    if current_role == "owner" or requested_role == "owner":
        raise MembershipRoleError("only workspace owners or organization admins can manage owners")


async def list_organization_members(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> MemberListResponse:
    _organization, actor_membership = await require_organization_member(
        session,
        user,
        organization_id,
    )
    rows = await repository.list_organization_members(
        session,
        organization_id=organization_id,
    )
    actor_role = organization_actor_role(user, actor_membership)
    return MemberListResponse(
        members=[
            member_response(membership, member, access_source="organization")
            for membership, member in rows
        ],
        current_user_id=user.id,
        can_manage=actor_role in ORG_ADMIN_ROLES,
        can_manage_owners=actor_role == "owner",
    )


async def update_organization_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MembershipRoleUpdate,
) -> MemberRead:
    _organization, actor_membership = await require_organization_admin(
        session,
        user,
        organization_id,
    )
    membership = await repository.get_organization_membership_by_id(
        session,
        organization_id,
        membership_id,
    )
    if membership is None:
        raise MembershipNotFoundError("organization membership not found")
    actor_role = organization_actor_role(user, actor_membership)
    require_organization_owner_action(
        actor_role,
        current_role=membership.role,
        requested_role=payload.role,
    )
    await repository.lock_organization_memberships(session, organization_id)
    if (
        membership.role == "owner"
        and payload.role != "owner"
        and await repository.count_active_organization_owners(session, organization_id) <= 1
    ):
        raise MembershipRoleError("an organization must keep at least one owner")
    membership.role = MembershipRole(payload.role)
    await session.flush()
    member = await users_repository.get_user_by_id(session, membership.user_id)
    if member is None:
        raise MembershipNotFoundError("organization member not found")
    return member_response(membership, member, access_source="organization")


async def remove_organization_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> None:
    _organization, actor_membership = await require_organization_admin(
        session,
        user,
        organization_id,
    )
    membership = await repository.get_organization_membership_by_id(
        session,
        organization_id,
        membership_id,
    )
    if membership is None:
        raise MembershipNotFoundError("organization membership not found")
    require_organization_owner_action(
        organization_actor_role(user, actor_membership),
        current_role=membership.role,
    )
    await repository.lock_organization_memberships(session, organization_id)
    if (
        membership.role == "owner"
        and await repository.count_active_organization_owners(session, organization_id) <= 1
    ):
        raise MembershipRoleError("an organization must keep at least one owner")
    await repository.lock_workspace_memberships_for_organization(session, organization_id)
    sole_owned_workspace_ids = (
        await repository.list_sole_owned_workspace_ids_for_organization_user(
            session,
            organization_id=organization_id,
            user_id=membership.user_id,
        )
    )
    if sole_owned_workspace_ids:
        raise MembershipRoleError(
            "transfer ownership of the member's workspaces before removing organization access"
        )
    membership.is_active = False
    await repository.deactivate_workspace_memberships_for_organization_user(
        session,
        organization_id=organization_id,
        user_id=membership.user_id,
    )
    await session.flush()


async def list_workspace_members(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> MemberListResponse:
    _workspace, organization_membership, workspace_membership = await require_workspace_member(
        session,
        user,
        organization_id,
        workspace_id,
    )
    direct_rows = await repository.list_workspace_members(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    organization_admin_rows = await repository.list_organization_admin_members(
        session,
        organization_id=organization_id,
    )
    organization_roles = {
        member.id: membership.role for membership, member in organization_admin_rows
    }
    direct_user_ids = {member.id for _membership, member in direct_rows}
    members = [
        member_response(
            membership,
            member,
            access_source="workspace",
            organization_role=organization_roles.get(member.id),
        )
        for membership, member in direct_rows
    ]
    members.extend(
        member_response(
            membership,
            member,
            access_source="organization",
            role="admin",
            organization_role=membership.role,
            editable=False,
        )
        for membership, member in organization_admin_rows
        if member.id not in direct_user_ids
    )
    members.sort(key=lambda item: (item.display_name.casefold(), str(item.user_id)))
    actor_role = workspace_actor_role(user, organization_membership, workspace_membership)
    return MemberListResponse(
        members=members,
        current_user_id=user.id,
        can_manage=actor_role in {"organization_admin", "owner", "admin"},
        can_manage_owners=actor_role in {"organization_admin", "owner"},
    )


async def update_workspace_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MembershipRoleUpdate,
) -> MemberRead:
    _workspace, organization_membership, actor_membership = await require_workspace_admin(
        session,
        user,
        organization_id,
        workspace_id,
    )
    membership = await repository.get_workspace_membership_by_id(
        session,
        workspace_id,
        membership_id,
    )
    if membership is None:
        raise MembershipNotFoundError("workspace membership not found")
    actor_role = workspace_actor_role(user, organization_membership, actor_membership)
    require_workspace_owner_action(
        actor_role,
        current_role=membership.role,
        requested_role=payload.role,
    )
    await repository.lock_workspace_memberships(session, workspace_id)
    if (
        membership.role == "owner"
        and payload.role != "owner"
        and await repository.count_active_workspace_owners(session, workspace_id) <= 1
    ):
        raise MembershipRoleError("a workspace must keep at least one owner")
    membership.role = MembershipRole(payload.role)
    await session.flush()
    member = await users_repository.get_user_by_id(session, membership.user_id)
    if member is None:
        raise MembershipNotFoundError("workspace member not found")
    return member_response(membership, member, access_source="workspace")


async def remove_workspace_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> None:
    _workspace, organization_membership, actor_membership = await require_workspace_admin(
        session,
        user,
        organization_id,
        workspace_id,
    )
    membership = await repository.get_workspace_membership_by_id(
        session,
        workspace_id,
        membership_id,
    )
    if membership is None:
        raise MembershipNotFoundError("workspace membership not found")
    require_workspace_owner_action(
        workspace_actor_role(user, organization_membership, actor_membership),
        current_role=membership.role,
    )
    await repository.lock_workspace_memberships(session, workspace_id)
    if (
        membership.role == "owner"
        and await repository.count_active_workspace_owners(session, workspace_id) <= 1
    ):
        raise MembershipRoleError("a workspace must keep at least one owner")
    membership.is_active = False
    await session.flush()


async def _ensure_invitation_target_available(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    email: str,
) -> None:
    existing_user = await users_repository.get_user_by_email(session, email)
    if existing_user is not None:
        organization_membership = await repository.get_organization_membership(
            session,
            organization_id,
            existing_user.id,
        )
        if workspace_id is None and organization_membership is not None:
            raise MembershipRoleError("user is already an organization member")
        if workspace_id is not None:
            if organization_membership and organization_membership.role in ORG_ADMIN_ROLES:
                raise MembershipRoleError(
                    "user already has workspace access through the organization"
                )
            if await repository.get_workspace_membership(session, workspace_id, existing_user.id):
                raise MembershipRoleError("user is already a workspace member")

    pending = await repository.get_pending_invitation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        email=email,
    )
    if pending is not None:
        if invitation_status(pending) == "pending":
            raise DuplicateInvitationError("a pending invitation already exists for this email")
        pending.status = "revoked"


async def _create_invitation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    email: str,
    role: str,
    invited_by_id: uuid.UUID,
) -> InvitationCreated:
    await _ensure_invitation_target_available(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        email=email,
    )
    token = generate_invitation_token()
    invitation = MembershipInvitation(
        organization_id=organization_id,
        workspace_id=workspace_id,
        scope_type="workspace" if workspace_id else "organization",
        email=email,
        role=role,
        token_hash=hash_invitation_token(token),
        status="pending",
        expires_at=datetime.now(UTC)
        + timedelta(seconds=get_settings().membership_invitation_ttl_seconds),
        invited_by_id=invited_by_id,
    )
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    return InvitationCreated(invitation=invitation_response(invitation), token=token)


async def create_organization_invitation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: InvitationCreate,
) -> InvitationCreated:
    _organization, actor_membership = await require_organization_admin(
        session,
        user,
        organization_id,
    )
    require_organization_owner_action(
        organization_actor_role(user, actor_membership),
        requested_role=payload.role,
    )
    return await _create_invitation(
        session,
        organization_id=organization_id,
        workspace_id=None,
        email=normalize_email(str(payload.email)),
        role=payload.role,
        invited_by_id=user.id,
    )


async def create_workspace_invitation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: InvitationCreate,
) -> InvitationCreated:
    _workspace, organization_membership, workspace_membership = await require_workspace_admin(
        session,
        user,
        organization_id,
        workspace_id,
    )
    require_workspace_owner_action(
        workspace_actor_role(user, organization_membership, workspace_membership),
        requested_role=payload.role,
    )
    return await _create_invitation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        email=normalize_email(str(payload.email)),
        role=payload.role,
        invited_by_id=user.id,
    )


async def list_scope_invitations(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> InvitationListResponse:
    if workspace_id is None:
        await require_organization_admin(session, user, organization_id)
    else:
        await require_workspace_admin(session, user, organization_id, workspace_id)
    invitations = await repository.list_invitations(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return InvitationListResponse(
        invitations=[invitation_response(invitation) for invitation in invitations]
    )


async def revoke_invitation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    invitation_id: uuid.UUID,
) -> None:
    if workspace_id is None:
        _organization, actor_membership = await require_organization_admin(
            session,
            user,
            organization_id,
        )
    else:
        _workspace, organization_membership, workspace_membership = await require_workspace_admin(
            session, user, organization_id, workspace_id
        )
    invitation = await repository.get_invitation_by_id(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
        for_update=True,
    )
    if invitation is None:
        raise InvitationNotFoundError("invitation not found")
    if workspace_id is None:
        require_organization_owner_action(
            organization_actor_role(user, actor_membership),
            current_role=invitation.role,
        )
    else:
        require_workspace_owner_action(
            workspace_actor_role(user, organization_membership, workspace_membership),
            current_role=invitation.role,
        )
    if invitation.status == "pending":
        invitation.status = "revoked"
        await session.flush()


async def _active_invitation(
    session: AsyncSession,
    token: str,
    *,
    for_update: bool = False,
) -> tuple[MembershipInvitation, Organization, Workspace | None]:
    invitation = await repository.get_invitation_by_token_hash(
        session,
        hash_invitation_token(token),
        for_update=for_update,
    )
    if invitation is None or invitation.status != "pending":
        raise InvitationNotFoundError("invitation is invalid or no longer available")
    if invitation_status(invitation) == "expired":
        raise InvitationExpiredError("invitation has expired")
    organization = await repository.get_organization_by_id(session, invitation.organization_id)
    if organization is None or organization.status != "active":
        raise OrganizationNotFoundError("organization not found")
    workspace = None
    if invitation.workspace_id is not None:
        workspace = await repository.get_workspace_by_id(session, invitation.workspace_id)
        if (
            workspace is None
            or workspace.organization_id != organization.id
            or workspace.status != "active"
        ):
            raise WorkspaceNotFoundError("workspace not found")
    return invitation, organization, workspace


async def _active_pending_invitation_by_id(
    session: AsyncSession,
    invitation_id: uuid.UUID,
    user: User,
    *,
    for_update: bool = False,
) -> tuple[MembershipInvitation, Organization, Workspace | None]:
    invitation = await repository.get_pending_invitation_for_email_by_id(
        session,
        invitation_id=invitation_id,
        email=normalize_email(user.email),
        for_update=for_update,
    )
    if invitation is None:
        raise InvitationNotFoundError("invitation is invalid or no longer available")
    if invitation_status(invitation) == "expired":
        raise InvitationExpiredError("invitation has expired")
    organization = await repository.get_organization_by_id(session, invitation.organization_id)
    if organization is None or organization.status != "active":
        raise OrganizationNotFoundError("organization not found")
    workspace = None
    if invitation.workspace_id is not None:
        workspace = await repository.get_workspace_by_id(session, invitation.workspace_id)
        if (
            workspace is None
            or workspace.organization_id != organization.id
            or workspace.status != "active"
        ):
            raise WorkspaceNotFoundError("workspace not found")
    return invitation, organization, workspace


async def list_pending_invitations_for_user(
    session: AsyncSession,
    user: User,
) -> PendingInvitationListResponse:
    rows = await repository.list_pending_invitations_for_email(
        session,
        email=normalize_email(user.email),
        now=datetime.now(UTC),
    )
    return PendingInvitationListResponse(
        invitations=[
            pending_invitation_response(invitation, organization, workspace)
            for invitation, organization, workspace in rows
        ]
    )


async def preview_invitation(
    session: AsyncSession,
    token: str,
    current_user: User | None,
) -> InvitationPreview:
    invitation, organization, workspace = await _active_invitation(session, token)
    settings = get_settings()
    return InvitationPreview(
        email=invitation.email,
        role=invitation.role,
        scope_type=cast(Literal["organization", "workspace"], invitation.scope_type),
        organization_id=organization.id,
        organization_name=organization.name,
        workspace_id=workspace.id if workspace else None,
        workspace_name=workspace.name if workspace else None,
        expires_at=invitation.expires_at,
        auth_mode=settings.auth_mode,
        oidc_provider_name=settings.oidc_provider_name,
        current_user_email=current_user.email if current_user else None,
    )


async def _accept_invitation(
    session: AsyncSession,
    invitation: MembershipInvitation,
    organization: Organization,
    workspace: Workspace | None,
    user: User,
) -> InvitationAcceptanceRead:
    if normalize_email(user.email) != normalize_email(invitation.email):
        logger.warning(
            "Membership invitation email mismatch.",
            extra={
                "invitation_id": str(invitation.id),
                "organization_id": str(organization.id),
                "workspace_id": str(workspace.id) if workspace else None,
                "scope_type": invitation.scope_type,
                "user_id": str(user.id),
            },
        )
        raise InvitationEmailMismatchError(
            "sign in with the email address that received this invitation"
        )
    organization_membership = await repository.get_organization_membership_any(
        session,
        organization.id,
        user.id,
    )
    if invitation.scope_type == "organization":
        if organization_membership is not None and organization_membership.is_active:
            raise MembershipRoleError("user is already an organization member")
        if organization_membership is None:
            organization_membership = OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=invitation.role,
                is_active=True,
            )
            session.add(organization_membership)
        else:
            organization_membership.role = MembershipRole(invitation.role)
            organization_membership.is_active = True
    else:
        assert workspace is not None
        if organization_membership is None:
            session.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role="member",
                    is_active=True,
                )
            )
        elif not organization_membership.is_active:
            organization_membership.role = MembershipRole.MEMBER
            organization_membership.is_active = True
        workspace_membership = await repository.get_workspace_membership_any(
            session,
            workspace.id,
            user.id,
        )
        if workspace_membership is not None and workspace_membership.is_active:
            raise MembershipRoleError("user is already a workspace member")
        if workspace_membership is None:
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=invitation.role,
                    is_active=True,
                )
            )
        else:
            workspace_membership.role = MembershipRole(invitation.role)
            workspace_membership.is_active = True

    now = datetime.now(UTC)
    invitation.status = "accepted"
    invitation.accepted_by_id = user.id
    invitation.accepted_at = now
    await session.flush()
    logger.info(
        "Accepted membership invitation.",
        extra={
            "invitation_id": str(invitation.id),
            "organization_id": str(organization.id),
            "workspace_id": str(workspace.id) if workspace else None,
            "scope_type": invitation.scope_type,
            "user_id": str(user.id),
            "role": invitation.role,
        },
    )
    return InvitationAcceptanceRead(
        organization_id=organization.id,
        organization_name=organization.name,
        workspace_id=workspace.id if workspace else None,
        workspace_name=workspace.name if workspace else None,
        user_id=user.id,
    )


async def accept_invitation(
    session: AsyncSession,
    token: str,
    user: User,
) -> InvitationAcceptanceRead:
    invitation, organization, workspace = await _active_invitation(
        session,
        token,
        for_update=True,
    )
    return await _accept_invitation(session, invitation, organization, workspace, user)


async def accept_pending_invitation(
    session: AsyncSession,
    invitation_id: uuid.UUID,
    user: User,
) -> InvitationAcceptanceRead:
    invitation, organization, workspace = await _active_pending_invitation_by_id(
        session,
        invitation_id,
        user,
        for_update=True,
    )
    return await _accept_invitation(session, invitation, organization, workspace, user)


async def register_from_invitation(
    session: AsyncSession,
    token: str,
    payload: InvitationRegistration,
) -> tuple[InvitationAcceptanceRead, User]:
    invitation, organization, workspace = await _active_invitation(
        session,
        token,
        for_update=True,
    )
    user = await create_user(
        session,
        UserCreate(
            email=invitation.email,
            password=payload.password,
            first_name=payload.first_name,
            last_name=payload.last_name,
        ),
    )
    acceptance = await _accept_invitation(session, invitation, organization, workspace, user)
    return acceptance, user
