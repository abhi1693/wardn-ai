from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import extract_api_token_key, verify_session_token
from app.db.session import get_db_session
from app.modules.users import repository
from app.modules.users.models import User
from app.modules.users.service import is_token_active


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
        token_prefix = extract_api_token_key(plaintext_token)
        api_token = (
            await repository.get_api_token_by_prefix(session, token_prefix)
            if token_prefix
            else None
        )
        if api_token and is_token_active(api_token, plaintext_token):
            user_id = api_token.user_id

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
