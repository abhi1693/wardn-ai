from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.guardrails.schemas import (
    GuardrailPolicyCreate,
    GuardrailPolicyListResponse,
    GuardrailPolicyRead,
    GuardrailPolicySimulationRequest,
    GuardrailPolicySimulationResponse,
    GuardrailPolicyUpdate,
    GuardrailSettingsRead,
    GuardrailSettingsUpdate,
    GuardrailStarterPoliciesRequest,
    GuardrailStarterPoliciesResponse,
)
from app.modules.guardrails.service import (
    create_guardrail_policy,
    create_starter_guardrail_policies,
    delete_guardrail_policy,
    get_guardrail_policy,
    get_guardrail_settings,
    list_guardrail_policies,
    simulate_guardrail_policy,
    update_guardrail_policy,
    update_guardrail_settings,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/guardrails/policies",
    tags=["workspace-guardrail-policies"],
)

workspace_settings_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/guardrails",
    tags=["workspace-guardrails"],
)


@workspace_settings_router.get(
    "/settings",
    response_model=GuardrailSettingsRead,
    operation_id="workspace_guardrails_get_settings",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_guardrail_settings_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailSettingsRead:
    return await get_guardrail_settings(
        session,
        current_user,
        organization_id,
        workspace_id=workspace_id,
    )


@workspace_settings_router.patch(
    "/settings",
    response_model=GuardrailSettingsRead,
    operation_id="workspace_guardrails_update_settings",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def update_workspace_guardrail_settings_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: GuardrailSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailSettingsRead:
    return await update_guardrail_settings(
        session,
        current_user,
        organization_id,
        payload,
        workspace_id=workspace_id,
    )


@workspace_settings_router.post(
    "/simulate",
    response_model=GuardrailPolicySimulationResponse,
    operation_id="workspace_guardrails_simulate_policy",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def simulate_workspace_guardrail_policy_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: GuardrailPolicySimulationRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailPolicySimulationResponse:
    return await simulate_guardrail_policy(
        session,
        current_user,
        organization_id,
        payload,
        workspace_id=workspace_id,
    )


@workspace_settings_router.post(
    "/starter-policies",
    response_model=GuardrailStarterPoliciesResponse,
    operation_id="workspace_guardrails_create_starter_policies",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_workspace_guardrail_starter_policies_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: GuardrailStarterPoliciesRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GuardrailStarterPoliciesResponse:
    return await create_starter_guardrail_policies(
        session,
        current_user,
        organization_id,
        payload,
        workspace_id=workspace_id,
    )


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
    return await list_guardrail_policies(
        session,
        current_user,
        organization_id,
        workspace_id=workspace_id,
    )


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
    return await create_guardrail_policy(
        session,
        current_user,
        organization_id,
        payload,
        workspace_id=workspace_id,
    )


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
    return await get_guardrail_policy(
        session,
        current_user,
        organization_id,
        policy_id,
        workspace_id=workspace_id,
    )


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
    return await update_guardrail_policy(
        session,
        current_user,
        organization_id,
        policy_id,
        payload,
        workspace_id=workspace_id,
    )


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
    await delete_guardrail_policy(
        session,
        current_user,
        organization_id,
        policy_id,
        workspace_id=workspace_id,
    )
