import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.licensing.models import LicenseInstallation

SINGLETON_KEY = "wardn"


async def get_or_create_installation(session: AsyncSession) -> LicenseInstallation:
    statement = (
        insert(LicenseInstallation)
        .values(
            singleton_key=SINGLETON_KEY,
            instance_id=uuid.uuid4(),
            signed_lease="",
            renewal_token="",
        )
        .on_conflict_do_nothing(index_elements=[LicenseInstallation.singleton_key])
    )
    await session.execute(statement)
    result = await session.execute(
        select(LicenseInstallation).where(
            LicenseInstallation.singleton_key == SINGLETON_KEY
        )
    )
    return result.scalar_one()


async def store_signed_lease(
    session: AsyncSession,
    installation: LicenseInstallation,
    *,
    signed_lease: str,
    renewal_token: str | None,
    imported_at: datetime,
) -> None:
    installation.signed_lease = signed_lease
    if renewal_token is not None:
        installation.renewal_token = renewal_token
    installation.lease_imported_at = imported_at
    await session.flush()
