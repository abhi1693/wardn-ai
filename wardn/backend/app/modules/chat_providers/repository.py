import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat_providers.models import (
    ChatProviderConnection,
    ChatProviderConnectionSecret,
    ChatProviderEvent,
    ChatProviderThread,
)


async def list_connections(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[ChatProviderConnection]:
    result = await session.execute(
        select(ChatProviderConnection)
        .where(
            ChatProviderConnection.organization_id == organization_id,
            ChatProviderConnection.workspace_id == workspace_id,
        )
        .order_by(ChatProviderConnection.created_at.desc(), ChatProviderConnection.id.desc())
    )
    return list(result.scalars().all())


async def list_active_whatsapp_connections(
    session: AsyncSession,
) -> list[ChatProviderConnection]:
    result = await session.execute(
        select(ChatProviderConnection)
        .where(
            ChatProviderConnection.provider == "whatsapp_local",
            ChatProviderConnection.is_active.is_(True),
        )
        .order_by(ChatProviderConnection.created_at.asc(), ChatProviderConnection.id.asc())
    )
    return list(result.scalars().all())


async def get_connection(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ChatProviderConnection | None:
    result = await session.execute(
        select(ChatProviderConnection).where(
            ChatProviderConnection.id == connection_id,
            ChatProviderConnection.organization_id == organization_id,
            ChatProviderConnection.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def get_active_connection_by_id(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
) -> ChatProviderConnection | None:
    result = await session.execute(
        select(ChatProviderConnection).where(
            ChatProviderConnection.id == connection_id,
            ChatProviderConnection.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_connection_secrets(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
) -> list[ChatProviderConnectionSecret]:
    result = await session.execute(
        select(ChatProviderConnectionSecret).where(
            ChatProviderConnectionSecret.connection_id == connection_id,
        )
    )
    return list(result.scalars().all())


async def delete_connection_secrets(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
) -> None:
    await session.execute(
        delete(ChatProviderConnectionSecret).where(
            ChatProviderConnectionSecret.connection_id == connection_id,
        )
    )


async def get_thread(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    external_thread_id: str,
) -> ChatProviderThread | None:
    result = await session.execute(
        select(ChatProviderThread).where(
            ChatProviderThread.connection_id == connection_id,
            ChatProviderThread.external_thread_id == external_thread_id,
        )
    )
    return result.scalar_one_or_none()


async def list_threads_for_connection(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    limit: int = 50,
) -> list[ChatProviderThread]:
    result = await session.execute(
        select(ChatProviderThread)
        .where(ChatProviderThread.connection_id == connection_id)
        .order_by(ChatProviderThread.updated_at.desc(), ChatProviderThread.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_event_by_external_id(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    external_event_id: str,
) -> ChatProviderEvent | None:
    result = await session.execute(
        select(ChatProviderEvent).where(
            ChatProviderEvent.connection_id == connection_id,
            ChatProviderEvent.external_event_id == external_event_id,
        )
    )
    return result.scalar_one_or_none()


async def list_events_for_connection(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    limit: int = 50,
) -> list[ChatProviderEvent]:
    result = await session.execute(
        select(ChatProviderEvent)
        .where(ChatProviderEvent.connection_id == connection_id)
        .order_by(ChatProviderEvent.created_at.desc(), ChatProviderEvent.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
