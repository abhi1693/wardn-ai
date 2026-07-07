import uuid

from sqlalchemy import func, select
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


async def count_credentials_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    if not hasattr(session, "execute"):
        return 0
    result = await session.execute(
        select(func.count()).select_from(LLMProviderCredential).where(
            LLMProviderCredential.organization_id == organization_id,
        )
    )
    return int(result.scalar_one())


async def count_credentials_for_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    if not hasattr(session, "execute"):
        return 0
    result = await session.execute(
        select(func.count()).select_from(LLMProviderCredential).where(
            LLMProviderCredential.workspace_id == workspace_id,
        )
    )
    return int(result.scalar_one())


async def count_credentials_for_user(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    if not hasattr(session, "execute"):
        return 0
    result = await session.execute(
        select(func.count()).select_from(LLMProviderCredential).where(
            LLMProviderCredential.organization_id == organization_id,
            LLMProviderCredential.user_id == user_id,
        )
    )
    return int(result.scalar_one())
