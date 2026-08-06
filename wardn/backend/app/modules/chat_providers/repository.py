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


async def list_outbound_events_for_agent_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> list[tuple[ChatProviderEvent, ChatProviderThread | None]]:
    result = await session.execute(
        select(ChatProviderEvent, ChatProviderThread)
        .outerjoin(ChatProviderThread, ChatProviderThread.id == ChatProviderEvent.thread_id)
        .where(
            ChatProviderEvent.organization_id == organization_id,
            ChatProviderEvent.workspace_id == workspace_id,
            ChatProviderEvent.direction == "outbound",
            ChatProviderEvent.payload["agentRunId"].as_string() == str(agent_run_id),
        )
        .order_by(ChatProviderEvent.created_at.asc(), ChatProviderEvent.id.asc())
    )
    return list(result.all())


async def has_provider_reply_for_agent_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        select(ChatProviderEvent.id)
        .where(
            ChatProviderEvent.organization_id == organization_id,
            ChatProviderEvent.workspace_id == workspace_id,
            ChatProviderEvent.direction == "outbound",
            ChatProviderEvent.payload["agentRunId"].as_string() == str(agent_run_id),
            ChatProviderEvent.payload["approvalRequest"].as_boolean().is_distinct_from(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_thread_connection_for_conversation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> tuple[ChatProviderThread, ChatProviderConnection] | None:
    result = await session.execute(
        select(ChatProviderThread, ChatProviderConnection)
        .join(ChatProviderConnection, ChatProviderConnection.id == ChatProviderThread.connection_id)
        .where(
            ChatProviderThread.organization_id == organization_id,
            ChatProviderThread.workspace_id == workspace_id,
            ChatProviderThread.conversation_id == conversation_id,
        )
        .order_by(ChatProviderThread.updated_at.desc(), ChatProviderThread.id.desc())
        .limit(1)
    )
    return result.one_or_none()
