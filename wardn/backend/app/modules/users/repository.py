import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.users.models import User, UserAPIToken


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User)
        .options(selectinload(User.local_credentials))
        .where(func.lower(User.email) == email.casefold())
    )
    return result.scalar_one_or_none()


async def get_api_token_by_prefix(session: AsyncSession, token_prefix: str) -> UserAPIToken | None:
    result = await session.execute(
        select(UserAPIToken).where(UserAPIToken.token_prefix == token_prefix)
    )
    return result.scalar_one_or_none()
