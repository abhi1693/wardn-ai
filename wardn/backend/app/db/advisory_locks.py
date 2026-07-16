from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def try_advisory_transaction_lock(session: AsyncSession, lock_id: int) -> bool:
    """Try to own one PostgreSQL advisory lock until the current transaction ends."""
    result = await session.execute(select(func.pg_try_advisory_xact_lock(lock_id)))
    return bool(result.scalar_one())
