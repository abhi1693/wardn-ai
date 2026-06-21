from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.schemas import ErrorResponse
from app.core.security import create_session_token
from app.db.session import get_db_session
from app.modules.users.exceptions import InvalidLoginError
from app.modules.users.schemas import LoginRequest, UserRead
from app.modules.users.service import authenticate_local_user

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
