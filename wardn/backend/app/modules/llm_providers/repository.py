import uuid

from sqlalchemy import select, update
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


async def clear_default_credentials(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    provider: str,
    visibility: str,
    workspace_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = update(LLMProviderCredential).where(
        LLMProviderCredential.organization_id == organization_id,
        LLMProviderCredential.provider == provider,
        LLMProviderCredential.visibility == visibility,
        LLMProviderCredential.is_default.is_(True),
    )
    if workspace_id is None:
        statement = statement.where(LLMProviderCredential.workspace_id.is_(None))
    else:
        statement = statement.where(LLMProviderCredential.workspace_id == workspace_id)
    if user_id is None:
        statement = statement.where(LLMProviderCredential.user_id.is_(None))
    else:
        statement = statement.where(LLMProviderCredential.user_id == user_id)
    if exclude_id is not None:
        statement = statement.where(LLMProviderCredential.id != exclude_id)
    await session.execute(statement.values(is_default=False))

