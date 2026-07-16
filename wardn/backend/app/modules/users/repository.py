import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
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


async def touch_api_token_last_used(
    session: AsyncSession,
    token_id: uuid.UUID,
    *,
    used_at: datetime,
    update_before: datetime,
) -> bool:
    result = await session.execute(
        update(UserAPIToken)
        .where(
            UserAPIToken.id == token_id,
            or_(
                UserAPIToken.last_used_at.is_(None),
                UserAPIToken.last_used_at < update_before,
            ),
        )
        .values(last_used_at=used_at)
    )
    return bool(result.rowcount)


async def list_user_api_tokens(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[UserAPIToken]:
    result = await session.execute(
        select(UserAPIToken)
        .where(UserAPIToken.user_id == user_id)
        .order_by(UserAPIToken.created_at.desc(), UserAPIToken.id.desc())
    )
    return list(result.scalars().all())


async def count_active_user_api_tokens(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(UserAPIToken).where(
            UserAPIToken.user_id == user_id,
            UserAPIToken.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def get_user_api_token_by_id(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
) -> UserAPIToken | None:
    result = await session.execute(
        select(UserAPIToken).where(
            UserAPIToken.id == token_id,
            UserAPIToken.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        delete(UserAPIToken).where(
            UserAPIToken.id == token_id,
            UserAPIToken.user_id == user_id,
        )
    )
    return result.rowcount > 0
