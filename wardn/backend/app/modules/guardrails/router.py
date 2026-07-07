from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.guardrails.exceptions import (
    DuplicateGuardrailPolicyError,
    GuardrailPolicyNotFoundError,
    InvalidGuardrailPolicyError,
)
from app.modules.guardrails.schemas import (
    GuardrailPolicyCreate,
    GuardrailPolicyListResponse,
    GuardrailPolicyRead,
    GuardrailPolicyUpdate,
)
from app.modules.guardrails.service import (
    create_guardrail_policy,
    delete_guardrail_policy,
    get_guardrail_policy,
    list_guardrail_policies,
    update_guardrail_policy,
)
from app.modules.limits.exceptions import LimitExceededError
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/guardrails/policies",
    tags=["workspace-guardrail-policies"],
)


def raise_access_error(exc: Exception) -> None:
    if isinstance(exc, (OrganizationNotFoundError, WorkspaceNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, (OrganizationAccessDeniedError, WorkspaceAccessDeniedError)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LimitExceededError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, InvalidGuardrailPolicyError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@workspace_router.get(
    "",
    response_model=GuardrailPolicyListResponse,
    operation_id="workspace_guardrail_policies_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_guardrail_policies_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailPolicyListResponse:
    try:
        return await list_guardrail_policies(
            session,
            current_user,
            organization_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise_access_error(exc)
        raise


@workspace_router.post(
    "",
    response_model=GuardrailPolicyRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="workspace_guardrail_policies_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_workspace_guardrail_policy_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: GuardrailPolicyCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailPolicyRead:
    try:
        response = await create_guardrail_policy(
            session,
            current_user,
            organization_id,
            payload,
            workspace_id=workspace_id,
        )
    except DuplicateGuardrailPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response


@workspace_router.get(
    "/{policy_id}",
    response_model=GuardrailPolicyRead,
    operation_id="workspace_guardrail_policies_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_guardrail_policy_route(
    organization_id: UUID,
    workspace_id: UUID,
    policy_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailPolicyRead:
    try:
        return await get_guardrail_policy(
            session,
            current_user,
            organization_id,
            policy_id,
            workspace_id=workspace_id,
        )
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@workspace_router.patch(
    "/{policy_id}",
    response_model=GuardrailPolicyRead,
    operation_id="workspace_guardrail_policies_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_workspace_guardrail_policy_route(
    organization_id: UUID,
    workspace_id: UUID,
    policy_id: UUID,
    payload: GuardrailPolicyUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailPolicyRead:
    try:
        response = await update_guardrail_policy(
            session,
            current_user,
            organization_id,
            policy_id,
            payload,
            workspace_id=workspace_id,
        )
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateGuardrailPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response


@workspace_router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_guardrail_policies_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_workspace_guardrail_policy_route(
    organization_id: UUID,
    workspace_id: UUID,
    policy_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        await delete_guardrail_policy(
            session,
            current_user,
            organization_id,
            policy_id,
            workspace_id=workspace_id,
        )
    except GuardrailPolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
