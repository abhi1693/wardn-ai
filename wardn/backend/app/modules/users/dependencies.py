from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import verify_session_token
from app.db.session import get_db_session
from app.modules.users import repository
from app.modules.users.models import User
from app.modules.users.service import authenticate_api_token


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    user_id = None
    settings = get_settings()
    session_token = request.cookies.get(settings.session_cookie_name)

    if session_token:
        user_id = verify_session_token(session_token)
    elif authorization and authorization.lower().startswith("bearer "):
        plaintext_token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
        authenticated = await authenticate_api_token(session, plaintext_token)
        if authenticated:
            user, _api_token = authenticated
            return user

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )

    user = await repository.get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user
