from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.schemas import ErrorResponse
from app.core.security import create_session_token
from app.db.session import get_db_session
from app.modules.users.dependencies import get_current_user
from app.modules.users.exceptions import (
    InvalidAPITokenScopeError,
    InvalidLoginError,
    OIDCAuthenticationError,
    OIDCConfigurationError,
    UserAPITokenNotFoundError,
)
from app.modules.users.models import User
from app.modules.users.oidc import (
    authorization_url,
    create_oidc_state,
    exchange_oidc_code,
    fetch_oidc_metadata,
    frontend_redirect_url,
    oidc_enabled,
    verify_oidc_identity,
    verify_oidc_state,
)
from app.modules.users.schemas import (
    AuthConfigRead,
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
    authenticate_oidc_identity,
    create_user_api_token,
    delete_user_api_token,
    list_user_api_tokens,
    update_user_api_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
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


def _clear_oidc_state_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.oidc_state_cookie_name,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        path="/",
    )


@router.get(
    "/config",
    response_model=AuthConfigRead,
    operation_id="auth_config",
)
async def auth_config() -> AuthConfigRead:
    settings = get_settings()
    oidc_configured = all(
        [
            settings.oidc_issuer_url.strip(),
            settings.oidc_client_id.strip(),
            settings.oidc_client_secret.strip(),
        ]
    )
    return AuthConfigRead(
        authMode=settings.auth_mode,
        localLoginEnabled=settings.auth_mode == "local",
        oidcLoginEnabled=settings.auth_mode == "oidc" and oidc_configured,
        oidcProviderName=settings.oidc_provider_name,
    )


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
    if get_settings().auth_mode != "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="local auth is disabled",
        )

    try:
        user = await authenticate_local_user(session, payload)
    except InvalidLoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        ) from exc

    _set_session_cookie(response, user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get(
    "/oidc/login",
    operation_id="auth_oidc_login",
    responses={
        status.HTTP_302_FOUND: {"description": "Redirect to the configured OIDC provider."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "OIDC authentication is not configured.",
        },
    },
)
async def oidc_login(
    redirect_to: Annotated[str | None, Query(alias="redirectTo")] = None,
) -> RedirectResponse:
    settings = get_settings()
    if not oidc_enabled(settings):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC auth is not enabled",
        )
    try:
        state, state_cookie = create_oidc_state(settings, redirect_to=redirect_to)
        metadata = await fetch_oidc_metadata(settings)
        location = authorization_url(settings, metadata, state)
    except OIDCConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    response = RedirectResponse(location, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=settings.oidc_state_cookie_name,
        value=state_cookie,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        max_age=10 * 60,
        path="/",
    )
    return response


@router.get(
    "/oidc/callback",
    operation_id="auth_oidc_callback",
    responses={
        status.HTTP_302_FOUND: {"description": "Redirect to the Wardn frontend."},
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "OIDC authentication failed.",
        },
    },
)
async def oidc_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = get_settings()
    if not oidc_enabled(settings):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC auth is not enabled",
        )
    if error:
        response = RedirectResponse(
            frontend_redirect_url(settings, "/login?error=oidc"),
            status_code=status.HTTP_302_FOUND,
        )
        _clear_oidc_state_cookie(response)
        return response
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing OIDC callback code or state",
        )

    state_cookie = request.cookies.get(settings.oidc_state_cookie_name)
    if not state_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing OIDC state",
        )

    try:
        oidc_state = verify_oidc_state(settings, state_cookie, state)
        metadata = await fetch_oidc_metadata(settings)
        token_response = await exchange_oidc_code(settings, metadata, code=code)
        identity = await verify_oidc_identity(
            settings,
            metadata,
            token_response,
            nonce=oidc_state.nonce,
        )
        user = await authenticate_oidc_identity(
            session,
            identity,
            auto_create_users=settings.oidc_auto_create_users,
            superuser_emails=settings.oidc_superuser_emails,
        )
    except OIDCConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except OIDCAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    response = RedirectResponse(
        frontend_redirect_url(settings, oidc_state.redirect_to),
        status_code=status.HTTP_302_FOUND,
    )
    _set_session_cookie(response, user)
    _clear_oidc_state_cookie(response)
    await session.commit()
    return response


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


@router.get(
    "/me",
    response_model=UserRead,
    operation_id="auth_me",
)
async def current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserRead:
    return UserRead.model_validate(current_user)


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
