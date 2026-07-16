import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import engine

logger = logging.getLogger(__name__)


async def database_is_ready(database_engine: AsyncEngine = engine) -> bool:
    try:
        async with database_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.warning("Database readiness check failed", exc_info=True)
        return False
    return True
