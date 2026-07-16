import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
DeferredSessionWork = Callable[[AsyncSession], Awaitable[None]]
DEFERRED_SESSION_WORK_KEY = "deferred_session_work"

settings = get_settings()


def create_database_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_pre_ping=settings.database_pool_pre_ping,
        pool_use_lifo=settings.database_pool_use_lifo,
    )


engine = create_database_engine(settings)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def defer_session_work(session: AsyncSession, work: DeferredSessionWork) -> None:
    session.info.setdefault(DEFERRED_SESSION_WORK_KEY, []).append(work)


async def run_deferred_session_work(session: AsyncSession) -> None:
    work_items = session.info.pop(DEFERRED_SESSION_WORK_KEY, [])
    for work in work_items:
        try:
            await work(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("Deferred database work failed.", exc_info=True)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            await run_deferred_session_work(session)
            raise
        else:
            await session.commit()
            await run_deferred_session_work(session)
