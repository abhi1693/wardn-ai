import uuid
from datetime import datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import (
    MembershipInvitation,
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.users.models import User


async def list_organizations_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Organization, OrganizationMembership | None]]:
    statement = (
        select(Organization, OrganizationMembership)
        .outerjoin(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Organization.id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.is_active.is_(True),
            ),
        )
        .order_by(Organization.name.asc())
    )
    if not include_archived:
        statement = statement.where(Organization.status != "archived")
    result = await session.execute(statement)
    return list(result.all())


async def list_joined_organizations_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Organization, OrganizationMembership]]:
    statement = (
        select(Organization, OrganizationMembership)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
        .order_by(Organization.name.asc())
    )
    if not include_archived:
        statement = statement.where(Organization.status != "archived")
    result = await session.execute(statement)
    return list(result.all())


async def get_organization_by_id(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> Organization | None:
    return await session.get(Organization, organization_id)


async def get_organization_by_slug(
    session: AsyncSession,
    slug: str,
) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()


async def get_organization_membership(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership | None:
    result = await session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_organization_membership_any(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership | None:
    result = await session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_organization_membership_by_id(
    session: AsyncSession,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> OrganizationMembership | None:
    result = await session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_organization_members(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[tuple[OrganizationMembership, User]]:
    result = await session.execute(
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(
            OrganizationMembership.role.desc(),
            func.lower(User.first_name).asc(),
            func.lower(User.last_name).asc(),
            func.lower(User.email).asc(),
            OrganizationMembership.id.asc(),
        )
    )
    return list(result.tuples().all())


async def lock_organization_memberships(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> None:
    await session.execute(
        select(OrganizationMembership.id)
        .where(OrganizationMembership.organization_id == organization_id)
        .with_for_update()
    )


async def count_active_organization_owners(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.role == "owner",
            OrganizationMembership.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def list_organization_admin_members(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[tuple[OrganizationMembership, User]]:
    result = await session.execute(
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.role.in_(("owner", "admin")),
            User.is_active.is_(True),
        )
        .order_by(
            OrganizationMembership.role.asc(),
            func.lower(User.first_name).asc(),
            func.lower(User.last_name).asc(),
            func.lower(User.email).asc(),
            OrganizationMembership.id.asc(),
        )
    )
    return list(result.all())


async def list_workspaces_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> list[Workspace]:
    statement = (
        select(Workspace)
        .where(Workspace.organization_id == organization_id)
        .order_by(Workspace.name.asc())
    )
    if not include_archived:
        statement = statement.where(Workspace.status != "archived")
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_workspaces_for_user(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Workspace, WorkspaceMembership | None]]:
    statement = (
        select(Workspace, WorkspaceMembership)
        .outerjoin(
            WorkspaceMembership,
            and_(
                WorkspaceMembership.workspace_id == Workspace.id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.is_active.is_(True),
            ),
        )
        .where(Workspace.organization_id == organization_id)
        .order_by(Workspace.name.asc())
    )
    if not include_archived:
        statement = statement.where(Workspace.status != "archived")
    result = await session.execute(statement)
    return list(result.all())


async def get_workspace_by_id(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> Workspace | None:
    return await session.get(Workspace, workspace_id)


async def get_workspace_by_slug(
    session: AsyncSession,
    organization_id: uuid.UUID,
    slug: str,
) -> Workspace | None:
    result = await session.execute(
        select(Workspace).where(
            Workspace.organization_id == organization_id,
            Workspace.slug == slug,
        )
    )
    return result.scalar_one_or_none()


async def get_default_workspace(session: AsyncSession) -> Workspace | None:
    result = await session.execute(
        select(Workspace)
        .join(Organization, Organization.id == Workspace.organization_id)
        .where(
            Organization.slug == "default",
            Workspace.slug == "default",
        )
        .order_by(Workspace.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_workspace_membership(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkspaceMembership | None:
    result = await session.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_workspace_membership_any(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkspaceMembership | None:
    result = await session.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_workspace_membership_by_id(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> WorkspaceMembership | None:
    result = await session.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.id == membership_id,
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def lock_workspace_memberships(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> None:
    await session.execute(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .with_for_update()
    )


async def count_active_workspace_owners(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == "owner",
            WorkspaceMembership.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def lock_workspace_memberships_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> None:
    await session.execute(
        select(WorkspaceMembership.id)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(Workspace.organization_id == organization_id)
        .with_for_update()
    )


async def list_sole_owned_workspace_ids_for_organization_user(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    owner_counts = (
        select(
            WorkspaceMembership.workspace_id.label("workspace_id"),
            func.count(WorkspaceMembership.id).label("owner_count"),
        )
        .where(
            WorkspaceMembership.role == "owner",
            WorkspaceMembership.is_active.is_(True),
        )
        .group_by(WorkspaceMembership.workspace_id)
        .subquery()
    )
    result = await session.execute(
        select(WorkspaceMembership.workspace_id)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .join(owner_counts, owner_counts.c.workspace_id == WorkspaceMembership.workspace_id)
        .where(
            Workspace.organization_id == organization_id,
            Workspace.status == "active",
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.role == "owner",
            WorkspaceMembership.is_active.is_(True),
            owner_counts.c.owner_count == 1,
        )
    )
    return list(result.scalars().all())


async def deactivate_workspace_memberships_for_organization_user(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    workspace_ids = select(Workspace.id).where(Workspace.organization_id == organization_id)
    await session.execute(
        update(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id.in_(workspace_ids),
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.is_active.is_(True),
        )
        .values(is_active=False)
    )


async def list_workspace_members(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[tuple[WorkspaceMembership, User]]:
    result = await session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            Workspace.organization_id == organization_id,
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(
            WorkspaceMembership.role.asc(),
            func.lower(User.first_name).asc(),
            func.lower(User.last_name).asc(),
            func.lower(User.email).asc(),
            WorkspaceMembership.id.asc(),
        )
    )
    return list(result.all())


async def list_invitations(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> list[MembershipInvitation]:
    statement = select(MembershipInvitation).where(
        MembershipInvitation.organization_id == organization_id,
        MembershipInvitation.workspace_id == workspace_id,
    )
    result = await session.execute(
        statement.order_by(MembershipInvitation.created_at.desc(), MembershipInvitation.id.desc())
    )
    return list(result.scalars().all())


async def get_invitation_by_id(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    invitation_id: uuid.UUID,
    for_update: bool = False,
) -> MembershipInvitation | None:
    statement = select(MembershipInvitation).where(
        MembershipInvitation.id == invitation_id,
        MembershipInvitation.organization_id == organization_id,
        MembershipInvitation.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_invitation_by_token_hash(
    session: AsyncSession,
    token_hash: str,
    *,
    for_update: bool = False,
) -> MembershipInvitation | None:
    statement = select(MembershipInvitation).where(MembershipInvitation.token_hash == token_hash)
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_pending_invitations_for_email(
    session: AsyncSession,
    *,
    email: str,
    now: datetime,
) -> list[tuple[MembershipInvitation, Organization, Workspace | None]]:
    result = await session.execute(
        select(MembershipInvitation, Organization, Workspace)
        .join(Organization, Organization.id == MembershipInvitation.organization_id)
        .outerjoin(Workspace, Workspace.id == MembershipInvitation.workspace_id)
        .where(
            func.lower(MembershipInvitation.email) == email.casefold(),
            MembershipInvitation.status == "pending",
            MembershipInvitation.expires_at > now,
            Organization.status == "active",
            (MembershipInvitation.workspace_id.is_(None)) | (Workspace.status == "active"),
        )
        .order_by(MembershipInvitation.created_at.desc(), MembershipInvitation.id.desc())
    )
    return list(result.tuples().all())


async def get_pending_invitation_for_email_by_id(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    email: str,
    for_update: bool = False,
) -> MembershipInvitation | None:
    statement = select(MembershipInvitation).where(
        MembershipInvitation.id == invitation_id,
        func.lower(MembershipInvitation.email) == email.casefold(),
        MembershipInvitation.status == "pending",
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_pending_invitation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    email: str,
) -> MembershipInvitation | None:
    result = await session.execute(
        select(MembershipInvitation).where(
            MembershipInvitation.organization_id == organization_id,
            MembershipInvitation.workspace_id == workspace_id,
            func.lower(MembershipInvitation.email) == email.casefold(),
            MembershipInvitation.status == "pending",
        )
    )
    return result.scalar_one_or_none()


async def count_active_workspaces_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Workspace)
        .where(
            Workspace.organization_id == organization_id,
            Workspace.status != "archived",
        )
    )
    return int(result.scalar_one())


async def count_active_workspaces_created_by_user(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Workspace)
        .where(
            Workspace.created_by_id == user_id,
            Workspace.status != "archived",
        )
    )
    return int(result.scalar_one())


async def count_active_workspaces_created_by_user_for_organization(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Workspace)
        .where(
            Workspace.organization_id == organization_id,
            Workspace.created_by_id == user_id,
            Workspace.status != "archived",
        )
    )
    return int(result.scalar_one())
