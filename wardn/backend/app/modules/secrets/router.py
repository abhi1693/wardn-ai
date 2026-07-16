from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.limits.exceptions import LimitExceededError
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.secrets.exceptions import (
    DuplicateSecretHandleError,
    DuplicateSecretStoreError,
    InvalidSecretHandleError,
    InvalidSecretStoreError,
    SecretHandleNotFoundError,
    SecretProviderError,
    SecretStoreNotFoundError,
)
from app.modules.secrets.schemas import (
    SecretHandleCreate,
    SecretHandleListResponse,
    SecretHandleRead,
    SecretHandleUpdate,
    SecretStoreCreate,
    SecretStoreListResponse,
    SecretStoreRead,
    SecretStoreUpdate,
    SecretValidationResponse,
)
from app.modules.secrets.service import (
    create_secret_handle,
    create_secret_store,
    delete_secret_handle,
    delete_secret_store,
    get_secret_handle,
    get_secret_store,
    list_secret_handles,
    list_secret_stores,
    update_secret_handle,
    update_secret_store,
    validate_secret_handle,
    validate_secret_store,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(
    prefix="/organizations/{organization_id}/secrets",
    tags=["secrets"],
)


def raise_access_error(exc: Exception) -> None:
    if isinstance(exc, (OrganizationNotFoundError, WorkspaceNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, (OrganizationAccessDeniedError, WorkspaceAccessDeniedError)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LimitExceededError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, (InvalidSecretStoreError, InvalidSecretHandleError, SecretProviderError)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@router.get(
    "/stores",
    response_model=SecretStoreListResponse,
    operation_id="secret_stores_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_secret_stores_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    workspace_id: Annotated[UUID | None, Query(alias="workspaceId")] = None,
) -> SecretStoreListResponse:
    try:
        return await list_secret_stores(
            session,
            current_user,
            organization_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.post(
    "/stores",
    response_model=SecretStoreRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="secret_stores_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_secret_store_route(
    organization_id: UUID,
    payload: SecretStoreCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretStoreRead:
    try:
        response = await create_secret_store(session, current_user, organization_id, payload)
    except DuplicateSecretStoreError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    return response


@router.get(
    "/stores/{store_id}",
    response_model=SecretStoreRead,
    operation_id="secret_stores_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_secret_store_route(
    organization_id: UUID,
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretStoreRead:
    try:
        return await get_secret_store(session, current_user, organization_id, store_id)
    except SecretStoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.patch(
    "/stores/{store_id}",
    response_model=SecretStoreRead,
    operation_id="secret_stores_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_secret_store_route(
    organization_id: UUID,
    store_id: UUID,
    payload: SecretStoreUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretStoreRead:
    try:
        response = await update_secret_store(
            session,
            current_user,
            organization_id,
            store_id,
            payload,
        )
    except SecretStoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateSecretStoreError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    return response


@router.delete(
    "/stores/{store_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="secret_stores_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_secret_store_route(
    organization_id: UUID,
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        await delete_secret_store(session, current_user, organization_id, store_id)
    except SecretStoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.post(
    "/stores/{store_id}/validate",
    response_model=SecretValidationResponse,
    operation_id="secret_stores_validate",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def validate_secret_store_route(
    organization_id: UUID,
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretValidationResponse:
    try:
        return await validate_secret_store(session, current_user, organization_id, store_id)
    except SecretStoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.get(
    "/handles",
    response_model=SecretHandleListResponse,
    operation_id="secret_handles_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_secret_handles_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    workspace_id: Annotated[UUID | None, Query(alias="workspaceId")] = None,
) -> SecretHandleListResponse:
    try:
        return await list_secret_handles(
            session,
            current_user,
            organization_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.post(
    "/handles",
    response_model=SecretHandleRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="secret_handles_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_secret_handle_route(
    organization_id: UUID,
    payload: SecretHandleCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretHandleRead:
    try:
        response = await create_secret_handle(session, current_user, organization_id, payload)
    except DuplicateSecretHandleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    return response


@router.get(
    "/handles/{handle_id}",
    response_model=SecretHandleRead,
    operation_id="secret_handles_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_secret_handle_route(
    organization_id: UUID,
    handle_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretHandleRead:
    try:
        return await get_secret_handle(session, current_user, organization_id, handle_id)
    except SecretHandleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.patch(
    "/handles/{handle_id}",
    response_model=SecretHandleRead,
    operation_id="secret_handles_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_secret_handle_route(
    organization_id: UUID,
    handle_id: UUID,
    payload: SecretHandleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretHandleRead:
    try:
        response = await update_secret_handle(
            session,
            current_user,
            organization_id,
            handle_id,
            payload,
        )
    except SecretHandleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateSecretHandleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    return response


@router.delete(
    "/handles/{handle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="secret_handles_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_secret_handle_route(
    organization_id: UUID,
    handle_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        await delete_secret_handle(session, current_user, organization_id, handle_id)
    except SecretHandleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.post(
    "/handles/{handle_id}/validate",
    response_model=SecretValidationResponse,
    operation_id="secret_handles_validate",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def validate_secret_handle_route(
    organization_id: UUID,
    handle_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SecretValidationResponse:
    try:
        return await validate_secret_handle(session, current_user, organization_id, handle_id)
    except SecretHandleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
