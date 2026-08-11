from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.modules.organizations import membership_service
from app.modules.organizations.schemas import (
    InvitationAcceptanceRead,
    InvitationCreate,
    InvitationCreated,
    InvitationListResponse,
    InvitationPreview,
    InvitationRegistration,
    MemberListResponse,
    MemberRead,
    MembershipRoleUpdate,
    PendingInvitationListResponse,
)
from app.modules.users.auth_router import set_session_cookie
from app.modules.users.dependencies import get_current_user, get_optional_current_user
from app.modules.users.models import User

organization_router = APIRouter(prefix="/organizations", tags=["memberships"])
invitation_router = APIRouter(prefix="/invitations", tags=["invitations"])


@organization_router.get(
    "/{organization_id}/members",
    response_model=MemberListResponse,
    operation_id="organization_members_list",
)
async def list_organization_members(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MemberListResponse:
    return await membership_service.list_organization_members(
        session,
        current_user,
        organization_id,
    )


@organization_router.patch(
    "/{organization_id}/members/{membership_id}",
    response_model=MemberRead,
    operation_id="organization_members_update",
)
async def update_organization_member(
    organization_id: UUID,
    membership_id: UUID,
    payload: MembershipRoleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MemberRead:
    return await membership_service.update_organization_member(
        session,
        current_user,
        organization_id,
        membership_id,
        payload,
    )


@organization_router.delete(
    "/{organization_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="organization_members_remove",
)
async def remove_organization_member(
    organization_id: UUID,
    membership_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await membership_service.remove_organization_member(
        session,
        current_user,
        organization_id,
        membership_id,
    )


@organization_router.get(
    "/{organization_id}/invitations",
    response_model=InvitationListResponse,
    operation_id="organization_invitations_list",
)
async def list_organization_invitations(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InvitationListResponse:
    return await membership_service.list_scope_invitations(
        session,
        current_user,
        organization_id,
        None,
    )


@organization_router.post(
    "/{organization_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="organization_invitations_create",
)
async def create_organization_invitation(
    organization_id: UUID,
    payload: InvitationCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InvitationCreated:
    return await membership_service.create_organization_invitation(
        session,
        current_user,
        organization_id,
        payload,
    )


@organization_router.delete(
    "/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="organization_invitations_revoke",
)
async def revoke_organization_invitation(
    organization_id: UUID,
    invitation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await membership_service.revoke_invitation(
        session,
        current_user,
        organization_id,
        None,
        invitation_id,
    )


@organization_router.get(
    "/{organization_id}/workspaces/{workspace_id}/members",
    response_model=MemberListResponse,
    operation_id="workspace_members_list",
)
async def list_workspace_members(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MemberListResponse:
    return await membership_service.list_workspace_members(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@organization_router.patch(
    "/{organization_id}/workspaces/{workspace_id}/members/{membership_id}",
    response_model=MemberRead,
    operation_id="workspace_members_update",
)
async def update_workspace_member(
    organization_id: UUID,
    workspace_id: UUID,
    membership_id: UUID,
    payload: MembershipRoleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MemberRead:
    return await membership_service.update_workspace_member(
        session,
        current_user,
        organization_id,
        workspace_id,
        membership_id,
        payload,
    )


@organization_router.delete(
    "/{organization_id}/workspaces/{workspace_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_members_remove",
)
async def remove_workspace_member(
    organization_id: UUID,
    workspace_id: UUID,
    membership_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await membership_service.remove_workspace_member(
        session,
        current_user,
        organization_id,
        workspace_id,
        membership_id,
    )


@organization_router.get(
    "/{organization_id}/workspaces/{workspace_id}/invitations",
    response_model=InvitationListResponse,
    operation_id="workspace_invitations_list",
)
async def list_workspace_invitations(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InvitationListResponse:
    return await membership_service.list_scope_invitations(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@organization_router.post(
    "/{organization_id}/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="workspace_invitations_create",
)
async def create_workspace_invitation(
    organization_id: UUID,
    workspace_id: UUID,
    payload: InvitationCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InvitationCreated:
    return await membership_service.create_workspace_invitation(
        session,
        current_user,
        organization_id,
        workspace_id,
        payload,
    )


@organization_router.delete(
    "/{organization_id}/workspaces/{workspace_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_invitations_revoke",
)
async def revoke_workspace_invitation(
    organization_id: UUID,
    workspace_id: UUID,
    invitation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await membership_service.revoke_invitation(
        session,
        current_user,
        organization_id,
        workspace_id,
        invitation_id,
    )


@invitation_router.get(
    "/pending",
    response_model=PendingInvitationListResponse,
    operation_id="invitations_pending_list",
)
async def list_pending_invitations(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PendingInvitationListResponse:
    return await membership_service.list_pending_invitations_for_user(session, current_user)


@invitation_router.post(
    "/pending/{invitation_id}/accept",
    response_model=InvitationAcceptanceRead,
    operation_id="invitations_pending_accept",
)
async def accept_pending_invitation(
    invitation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InvitationAcceptanceRead:
    return await membership_service.accept_pending_invitation(
        session,
        invitation_id,
        current_user,
    )


@invitation_router.get(
    "/{token}",
    response_model=InvitationPreview,
    operation_id="invitations_preview",
)
async def preview_invitation(
    token: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> InvitationPreview:
    return await membership_service.preview_invitation(session, token, current_user)


@invitation_router.post(
    "/{token}/accept",
    response_model=InvitationAcceptanceRead,
    operation_id="invitations_accept",
)
async def accept_invitation(
    token: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InvitationAcceptanceRead:
    return await membership_service.accept_invitation(session, token, current_user)


@invitation_router.post(
    "/{token}/register",
    response_model=InvitationAcceptanceRead,
    operation_id="invitations_register",
)
async def register_from_invitation(
    token: str,
    payload: InvitationRegistration,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvitationAcceptanceRead:
    if get_settings().auth_mode != "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account registration is disabled for OIDC authentication",
        )
    acceptance, user = await membership_service.register_from_invitation(
        session,
        token,
        payload,
    )
    set_session_cookie(response, user)
    return acceptance
