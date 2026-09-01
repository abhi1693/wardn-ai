import asyncio
import logging
from contextlib import suppress

from app.core.config import Settings, get_settings
from app.db.session import AsyncSessionLocal
from app.modules.licensing.service import renew_installed_license

logger = logging.getLogger(__name__)


async def license_renewal_loop(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await renew_installed_license(session, settings=settings)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Automatic license renewal failed; the installed lease remains in effect.",
                exc_info=True,
            )
        await asyncio.sleep(settings.licensing_renewal_interval_seconds)


def start_license_renewal_worker(settings: Settings | None = None) -> asyncio.Task | None:
    settings = settings or get_settings()
    if not settings.licensing_activation_key.get_secret_value().strip():
        return None
    return asyncio.create_task(license_renewal_loop(settings))


async def stop_license_renewal_worker(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
