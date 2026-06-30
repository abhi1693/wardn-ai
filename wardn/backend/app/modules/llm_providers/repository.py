import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.llm_providers.models import LLMProviderCredential


async def list_credentials(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[LLMProviderCredential]:
    result = await session.execute(
        select(LLMProviderCredential)
        .where(LLMProviderCredential.organization_id == organization_id)
        .order_by(
            LLMProviderCredential.provider.asc(),
            LLMProviderCredential.name.asc(),
        )
    )
    return list(result.scalars().all())


async def get_credential(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> LLMProviderCredential | None:
    result = await session.execute(
        select(LLMProviderCredential).where(
            LLMProviderCredential.id == credential_id,
            LLMProviderCredential.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_credential_by_name(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    name: str,
) -> LLMProviderCredential | None:
    result = await session.execute(
        select(LLMProviderCredential).where(
            LLMProviderCredential.organization_id == organization_id,
            LLMProviderCredential.name == name,
        )
    )
    return result.scalar_one_or_none()
