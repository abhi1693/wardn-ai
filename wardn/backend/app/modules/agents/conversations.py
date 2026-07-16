from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

AgentSessionFactory = Callable[[], AsyncSession]


@asynccontextmanager
async def agent_stream_unit_of_work(
    session_factory: AgentSessionFactory | None = None,
) -> AsyncIterator[AsyncSession]:
    factory = session_factory or AsyncSessionLocal
    async with factory() as session:
        async with session.begin():
            yield session
