import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)


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
