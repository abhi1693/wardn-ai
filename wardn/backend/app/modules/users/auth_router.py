from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.schemas import ErrorResponse
from app.core.security import create_session_token
from app.db.session import get_db_session
from app.modules.users.dependencies import get_current_user
from app.modules.users.exceptions import (
    InvalidAPITokenScopeError,
    InvalidLoginError,
    UserAPITokenNotFoundError,
)
from app.modules.users.models import User
from app.modules.users.schemas import (
    LoginRequest,
    UserAPITokenCreate,
    UserAPITokenCreated,
    UserAPITokenListResponse,
    UserAPITokenRead,
    UserAPITokenUpdate,
    UserRead,
)
from app.modules.users.service import (
    authenticate_local_user,
    create_user_api_token,
    delete_user_api_token,
    list_user_api_tokens,
    update_user_api_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=UserRead,
    operation_id="auth_login",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Invalid email or password.",
        },
    },
)
async def login(
    payload: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    try:
        user = await authenticate_local_user(session, payload)
    except InvalidLoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        ) from exc

    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(user.id),
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="auth_logout",
)
async def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        path="/",
    )


@router.post(
    "/api-tokens",
    response_model=UserAPITokenCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="auth_create_api_token",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Requested token scope is not available to the current user.",
        },
    },
)
async def create_api_token(
    payload: UserAPITokenCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserAPITokenCreated:
    try:
        record, token = await create_user_api_token(session, current_user.id, payload)
    except InvalidAPITokenScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(record)
    return UserAPITokenCreated(
        token=token,
        record=UserAPITokenRead.model_validate(record),
    )


@router.get(
    "/api-tokens",
    response_model=UserAPITokenListResponse,
    operation_id="auth_list_api_tokens",
)
async def list_api_tokens(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserAPITokenListResponse:
    records = await list_user_api_tokens(session, current_user.id)
    return UserAPITokenListResponse(
        tokens=[UserAPITokenRead.model_validate(record) for record in records]
    )


@router.patch(
    "/api-tokens/{token_id}",
    response_model=UserAPITokenRead,
    operation_id="auth_update_api_token",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Requested token scope is not available to the current user.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "API token not found.",
        },
    },
)
async def update_api_token(
    token_id: UUID,
    payload: UserAPITokenUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserAPITokenRead:
    try:
        record = await update_user_api_token(session, current_user.id, token_id, payload)
    except InvalidAPITokenScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UserAPITokenNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(record)
    return UserAPITokenRead.model_validate(record)


@router.delete(
    "/api-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="auth_delete_api_token",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "API token not found.",
        },
    },
)
async def delete_api_token(
    token_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        await delete_user_api_token(session, current_user.id, token_id)
    except UserAPITokenNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
