from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.llm_providers.exceptions import (
    DuplicateLLMProviderCredentialError,
    InvalidLLMProviderCredentialAuthError,
    InvalidLLMProviderCredentialScopeError,
    LLMProviderCredentialNotFoundError,
)
from app.modules.llm_providers.schemas import (
    LLMProviderCredentialCreate,
    LLMProviderCredentialListResponse,
    LLMProviderCredentialRead,
    LLMProviderCredentialUpdate,
    LLMProviderModelListResponse,
)
from app.modules.llm_providers.service import (
    create_provider_credential,
    delete_provider_credential,
    list_provider_credential_models,
    list_provider_credentials,
    update_provider_credential,
)
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(
    prefix="/organizations/{organization_id}/llm/provider-credentials",
    tags=["llm-provider-credentials"],
)


def raise_access_error(exc: Exception) -> None:
    if isinstance(exc, (OrganizationNotFoundError, WorkspaceNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, (OrganizationAccessDeniedError, WorkspaceAccessDeniedError)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, InvalidLLMProviderCredentialScopeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, InvalidLLMProviderCredentialAuthError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


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
    try:
        return await list_provider_credentials(session, current_user, organization_id)
    except Exception as exc:
        raise_access_error(exc)
        raise


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
    try:
        response = await create_provider_credential(
            session,
            current_user,
            organization_id,
            payload,
        )
    except DuplicateLLMProviderCredentialError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response


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
    try:
        response = await update_provider_credential(
            session,
            current_user,
            organization_id,
            credential_id,
            payload,
        )
    except LLMProviderCredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateLLMProviderCredentialError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response


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
    try:
        return await list_provider_credential_models(
            session,
            current_user,
            organization_id,
            credential_id,
        )
    except LLMProviderCredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


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
    try:
        await delete_provider_credential(session, current_user, organization_id, credential_id)
    except LLMProviderCredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
