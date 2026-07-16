from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.llm_providers.schemas import (
    ChatGPTDeviceAuthorizationCompleteRequest,
    ChatGPTDeviceAuthorizationCompleteResponse,
    ChatGPTDeviceAuthorizationStartResponse,
    LLMProviderCredentialCreate,
    LLMProviderCredentialListResponse,
    LLMProviderCredentialRead,
    LLMProviderCredentialUpdate,
    LLMProviderCredentialValidationResponse,
    LLMProviderModelListResponse,
)
from app.modules.llm_providers.service import (
    complete_chatgpt_device_authorization,
    create_provider_credential,
    delete_provider_credential,
    list_provider_credential_models,
    list_provider_credentials,
    start_chatgpt_device_authorization,
    update_provider_credential,
    validate_provider_credential_by_id,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(
    prefix="/organizations/{organization_id}/llm/provider-credentials",
    tags=["llm-provider-credentials"],
)


@router.get(
    "",
    response_model=LLMProviderCredentialListResponse,
    operation_id="llm_provider_credentials_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_provider_credentials_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMProviderCredentialListResponse:
    return await list_provider_credentials(session, current_user, organization_id)


@router.post(
    "",
    response_model=LLMProviderCredentialRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="llm_provider_credentials_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_provider_credential_route(
    organization_id: UUID,
    payload: LLMProviderCredentialCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMProviderCredentialRead:
    return await create_provider_credential(
        session,
        current_user,
        organization_id,
        payload,
    )


@router.post(
    "/chatgpt/device/start",
    response_model=ChatGPTDeviceAuthorizationStartResponse,
    operation_id="llm_provider_credentials_chatgpt_device_start",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def start_chatgpt_device_authorization_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatGPTDeviceAuthorizationStartResponse:
    return await start_chatgpt_device_authorization(session, current_user, organization_id)


@router.post(
    "/chatgpt/device/complete",
    response_model=ChatGPTDeviceAuthorizationCompleteResponse,
    operation_id="llm_provider_credentials_chatgpt_device_complete",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def complete_chatgpt_device_authorization_route(
    organization_id: UUID,
    payload: ChatGPTDeviceAuthorizationCompleteRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatGPTDeviceAuthorizationCompleteResponse:
    return await complete_chatgpt_device_authorization(
        session,
        current_user,
        organization_id,
        payload,
    )


@router.patch(
    "/{credential_id}",
    response_model=LLMProviderCredentialRead,
    operation_id="llm_provider_credentials_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_provider_credential_route(
    organization_id: UUID,
    credential_id: UUID,
    payload: LLMProviderCredentialUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMProviderCredentialRead:
    return await update_provider_credential(
        session,
        current_user,
        organization_id,
        credential_id,
        payload,
    )


@router.get(
    "/{credential_id}/models",
    response_model=LLMProviderModelListResponse,
    operation_id="llm_provider_credentials_list_models",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_provider_credential_models_route(
    organization_id: UUID,
    credential_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMProviderModelListResponse:
    return await list_provider_credential_models(
        session,
        current_user,
        organization_id,
        credential_id,
    )


@router.post(
    "/{credential_id}/validate",
    response_model=LLMProviderCredentialValidationResponse,
    operation_id="llm_provider_credentials_validate",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def validate_provider_credential_route(
    organization_id: UUID,
    credential_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMProviderCredentialValidationResponse:
    return await validate_provider_credential_by_id(
        session,
        current_user,
        organization_id,
        credential_id,
    )


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="llm_provider_credentials_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_provider_credential_route(
    organization_id: UUID,
    credential_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await delete_provider_credential(session, current_user, organization_id, credential_id)
