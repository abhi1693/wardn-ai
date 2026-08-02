import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
from app.modules.agents import repository as agent_repository
from app.modules.agents import service as agent_service
from app.modules.agents.conversations import AgentSessionFactory
from app.modules.agents.mappers import text_parts
from app.modules.agents.schemas import AgentChatMessage, AgentChatRequest
from app.modules.chat_providers import repository, telegram, whatsapp_local
from app.modules.chat_providers.exceptions import (
    ChatProviderConnectionNotFoundError,
    ChatProviderDeliveryError,
    ChatProviderWebhookAuthError,
    DuplicateChatProviderConnectionError,
    InvalidChatProviderConnectionError,
)
from app.modules.chat_providers.models import (
    ChatProviderConnection,
    ChatProviderConnectionSecret,
    ChatProviderEvent,
    ChatProviderThread,
)
from app.modules.chat_providers.schemas import (
    ChatProviderConnectionCreate,
    ChatProviderConnectionListResponse,
    ChatProviderConnectionRead,
    ChatProviderConnectionUpdate,
    ChatProviderWebhookResponse,
    TelegramProviderConfig,
    WhatsAppLocalProviderConfig,
)
from app.modules.organizations.service import require_workspace_admin
from app.modules.secrets.service import resolve_secret
from app.modules.users.models import User
from app.modules.users.repository import get_user_by_id

logger = logging.getLogger(__name__)

PROVIDER_TELEGRAM = "telegram"
PROVIDER_WHATSAPP_LOCAL = "whatsapp_local"
SECRET_ACCESS_TOKEN = "access_token"
SECRET_BOT_TOKEN = "bot_token"
SECRET_OUTBOUND_SECRET = "outbound_secret"
SECRET_SIGNING_SECRET = "signing_secret"
SECRET_WEBHOOK_SECRET = "webhook_secret"
SUPPORTED_PROVIDERS = {PROVIDER_TELEGRAM, PROVIDER_WHATSAPP_LOCAL}
CHAT_PROVIDER_DUPLICATE_CONSTRAINTS = {
    "uq_chat_provider_connections_workspace_name",
    "uq_chat_provider_connections_workspace_provider_external",
}
PROVIDER_ASSISTANT_EMPTY_REPLY = (
    "I processed that request, but there was no text response to send back here."
)


@dataclass(frozen=True)
class ProviderTextMessage:
    event_id: str
    external_thread_id: str
    external_user_id: str
    external_user_display_name: str
    text: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class ProviderUnsupportedMessage:
    event_id: str
    external_thread_id: str
    external_user_id: str
    external_user_display_name: str
    message_type: str
    raw: dict[str, Any]


def provider_config_model(
    provider: str,
) -> type[TelegramProviderConfig] | type[WhatsAppLocalProviderConfig]:
    if provider == PROVIDER_TELEGRAM:
        return TelegramProviderConfig
    if provider == PROVIDER_WHATSAPP_LOCAL:
        return WhatsAppLocalProviderConfig
    raise InvalidChatProviderConnectionError("unsupported chat provider")


def normalize_connection_config(provider: str, config: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return provider_config_model(provider).model_validate(config or {}).model_dump(
            by_alias=False
        )
    except ValidationError as exc:
        raise InvalidChatProviderConnectionError("invalid chat provider config") from exc


def public_connection_config(connection: ChatProviderConnection) -> dict[str, Any]:
    return normalize_connection_config(connection.provider, dict(connection.config or {}))


def normalized_config(connection: ChatProviderConnection) -> dict[str, Any]:
    return normalize_connection_config(connection.provider, dict(connection.config or {}))


def sender_allowed(connection: ChatProviderConnection, message: ProviderTextMessage) -> bool:
    config = normalized_config(connection)
    if bool(config.get("allow_all_senders")):
        return True
    allowed_senders = {str(item).strip() for item in config.get("allowed_sender_ids", [])}
    allowed_chats = {str(item).strip() for item in config.get("allowed_chat_ids", [])}
    return (
        bool(message.external_user_id and message.external_user_id in allowed_senders)
        or bool(message.external_thread_id and message.external_thread_id in allowed_chats)
    )


def normalize_secret_handle_ids(
    secret_handle_ids: dict[str, uuid.UUID] | None,
) -> dict[str, uuid.UUID]:
    return {
        key.strip().lower(): value
        for key, value in (secret_handle_ids or {}).items()
        if key.strip()
    }


def required_secret_keys(provider: str) -> set[str]:
    if provider == PROVIDER_TELEGRAM:
        return {SECRET_BOT_TOKEN, SECRET_WEBHOOK_SECRET}
    if provider == PROVIDER_WHATSAPP_LOCAL:
        return {SECRET_WEBHOOK_SECRET}
    raise InvalidChatProviderConnectionError("unsupported chat provider")


async def connection_secret_handle_ids(
    session: AsyncSession,
    connection: ChatProviderConnection,
) -> dict[str, uuid.UUID]:
    secrets = await repository.list_connection_secrets(session, connection_id=connection.id)
    return {item.purpose: item.secret_handle_id for item in secrets}


async def connection_secret_handle_id(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *purposes: str,
) -> uuid.UUID | None:
    secret_handle_ids = await connection_secret_handle_ids(session, connection)
    for purpose in purposes:
        secret_handle_id = secret_handle_ids.get(purpose)
        if secret_handle_id is not None:
            return secret_handle_id
    return None


async def replace_connection_secrets(
    session: AsyncSession,
    connection: ChatProviderConnection,
    secret_handle_ids: dict[str, uuid.UUID],
) -> None:
    await repository.delete_connection_secrets(session, connection_id=connection.id)
    for purpose, secret_handle_id in sorted(secret_handle_ids.items()):
        session.add(
            ChatProviderConnectionSecret(
                organization_id=connection.organization_id,
                workspace_id=connection.workspace_id,
                connection_id=connection.id,
                purpose=purpose,
                secret_handle_id=secret_handle_id,
            )
        )
    await session.flush()


async def connection_response(
    session: AsyncSession,
    connection: ChatProviderConnection,
) -> ChatProviderConnectionRead:
    return ChatProviderConnectionRead(
        id=connection.id,
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        created_by_id=connection.created_by_id,
        provider=connection.provider,
        name=connection.name,
        external_id=connection.external_id,
        display_name=connection.display_name,
        secret_handle_ids=await connection_secret_handle_ids(session, connection),
        config=public_connection_config(connection),
        is_active=connection.is_active,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


async def validate_secret_handles(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    provider: str,
    secret_handle_ids: dict[str, uuid.UUID],
) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise InvalidChatProviderConnectionError("unsupported chat provider")

    missing_keys = required_secret_keys(provider) - set(secret_handle_ids)
    if missing_keys:
        raise InvalidChatProviderConnectionError(
            f"chat provider is missing required secrets: {', '.join(sorted(missing_keys))}"
        )

    for handle_id in set(secret_handle_ids.values()):
        await resolve_secret(
            session,
            organization_id,
            handle_id,
            workspace_id=workspace_id,
        )


async def list_workspace_chat_provider_connections(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> ChatProviderConnectionListResponse:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    connections = await repository.list_connections(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return ChatProviderConnectionListResponse(
        connections=[
            await connection_response(session, connection)
            for connection in connections
        ]
    )


async def get_workspace_chat_provider_connection(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ChatProviderConnectionRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    connection = await repository.get_connection(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise ChatProviderConnectionNotFoundError("chat provider connection not found")
    return await connection_response(session, connection)


async def create_workspace_chat_provider_connection(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: ChatProviderConnectionCreate,
) -> ChatProviderConnectionRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    config = normalize_connection_config(payload.provider, payload.config)
    secret_handle_ids = normalize_secret_handle_ids(payload.secret_handle_ids)
    await validate_secret_handles(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=payload.provider,
        secret_handle_ids=secret_handle_ids,
    )
    connection = ChatProviderConnection(
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        provider=payload.provider,
        name=payload.name,
        external_id=payload.external_id,
        display_name=payload.display_name,
        config=config,
        is_active=True,
    )
    session.add(connection)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, CHAT_PROVIDER_DUPLICATE_CONSTRAINTS):
            raise DuplicateChatProviderConnectionError(
                "chat provider connection already exists"
            ) from exc
        raise
    await replace_connection_secrets(session, connection, secret_handle_ids)
    await session.refresh(connection)
    return await connection_response(session, connection)


async def update_workspace_chat_provider_connection(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    payload: ChatProviderConnectionUpdate,
) -> ChatProviderConnectionRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    connection = await repository.get_connection(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise ChatProviderConnectionNotFoundError("chat provider connection not found")

    next_secret_handle_ids = await connection_secret_handle_ids(session, connection)
    if payload.secret_handle_ids is not None:
        next_secret_handle_ids = normalize_secret_handle_ids(payload.secret_handle_ids)
        await validate_secret_handles(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            provider=connection.provider,
            secret_handle_ids=next_secret_handle_ids,
        )
    if payload.name is not None:
        connection.name = payload.name
    if payload.external_id is not None:
        connection.external_id = payload.external_id
    if payload.display_name is not None:
        connection.display_name = payload.display_name
    if payload.config is not None:
        connection.config = normalize_connection_config(connection.provider, payload.config)
    if payload.is_active is not None:
        connection.is_active = payload.is_active
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, CHAT_PROVIDER_DUPLICATE_CONSTRAINTS):
            raise DuplicateChatProviderConnectionError(
                "chat provider connection already exists"
            ) from exc
        raise
    if payload.secret_handle_ids is not None:
        await replace_connection_secrets(session, connection, next_secret_handle_ids)
    await session.refresh(connection)
    return await connection_response(session, connection)


async def delete_workspace_chat_provider_connection(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> None:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    connection = await repository.get_connection(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise ChatProviderConnectionNotFoundError("chat provider connection not found")
    await session.delete(connection)
    await session.flush()


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


async def active_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    *,
    provider: str,
) -> ChatProviderConnection:
    connection = await repository.get_active_connection_by_id(
        session,
        connection_id=connection_id,
    )
    if connection is None or connection.provider != provider:
        raise ChatProviderConnectionNotFoundError("chat provider connection not found")
    return connection


async def validate_webhook_secret(
    session: AsyncSession,
    connection: ChatProviderConnection,
    provided_secret: str | None,
) -> None:
    if not provided_secret:
        raise ChatProviderWebhookAuthError("missing chat provider webhook secret")
    secret_handle_id = await connection_secret_handle_id(
        session,
        connection,
        SECRET_WEBHOOK_SECRET,
    )
    if secret_handle_id is None:
        raise ChatProviderWebhookAuthError("chat provider webhook secret is not configured")
    expected = await resolve_secret(
        session,
        connection.organization_id,
        secret_handle_id,
        workspace_id=connection.workspace_id,
    )
    if not hmac_compare(expected.value, provided_secret):
        raise ChatProviderWebhookAuthError("invalid chat provider webhook secret")


def decode_webhook_body(body: bytes, *, provider_name: str) -> dict[str, Any] | list[Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidChatProviderConnectionError(
            f"invalid {provider_name} webhook payload"
        ) from exc
    if not isinstance(payload, dict | list):
        raise InvalidChatProviderConnectionError(f"invalid {provider_name} webhook payload")
    return payload


def provider_message_from_telegram(
    message: telegram.TelegramTextMessage,
) -> ProviderTextMessage:
    return ProviderTextMessage(
        event_id=message.event_id,
        external_thread_id=message.chat_id,
        external_user_id=message.user_id,
        external_user_display_name=message.user_display_name,
        text=message.text,
        raw=message.raw,
    )


def provider_unsupported_from_telegram(
    message: telegram.TelegramUnsupportedMessage,
) -> ProviderUnsupportedMessage:
    return ProviderUnsupportedMessage(
        event_id=message.event_id,
        external_thread_id=message.chat_id,
        external_user_id=message.user_id,
        external_user_display_name="",
        message_type=message.message_type,
        raw=message.raw,
    )


def provider_message_from_whatsapp_local(
    message: whatsapp_local.WhatsAppLocalTextMessage,
) -> ProviderTextMessage:
    return ProviderTextMessage(
        event_id=message.event_id,
        external_thread_id=message.chat_id,
        external_user_id=message.sender_id,
        external_user_display_name=message.sender_display_name,
        text=message.text,
        raw=message.raw,
    )


def provider_unsupported_from_whatsapp_local(
    message: whatsapp_local.WhatsAppLocalUnsupportedMessage,
) -> ProviderUnsupportedMessage:
    return ProviderUnsupportedMessage(
        event_id=message.event_id,
        external_thread_id=message.chat_id,
        external_user_id=message.sender_id,
        external_user_display_name=message.sender_display_name,
        message_type=message.message_type,
        raw=message.raw,
    )


async def handle_telegram_webhook(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    body: bytes,
    secret_token_header: str | None,
    session_factory: AgentSessionFactory | None = None,
) -> ChatProviderWebhookResponse:
    connection = await active_connection(session, connection_id, provider=PROVIDER_TELEGRAM)
    await validate_webhook_secret(session, connection, secret_token_header)
    payload = decode_webhook_body(body, provider_name="Telegram")
    if not isinstance(payload, dict):
        raise InvalidChatProviderConnectionError("invalid Telegram webhook payload")

    response = ChatProviderWebhookResponse()
    unsupported = telegram.unsupported_message(payload)
    if unsupported is not None:
        response.received += 1
        handled = await record_unsupported_provider_message(
            session,
            connection,
            provider_unsupported_from_telegram(unsupported),
        )
        if handled:
            response.ignored += 1
        else:
            response.duplicates += 1
        return response

    text_message = telegram.text_message(payload)
    if text_message is None:
        response.received += 1
        response.ignored += 1
        return response

    response.received += 1
    try:
        processed = await process_provider_text_message(
            session,
            connection,
            provider_message_from_telegram(text_message),
            session_factory=session_factory,
        )
    except Exception:
        response.failed += 1
        logger.exception(
            "Failed to process Telegram chat provider message.",
            extra={
                "organization_id": str(connection.organization_id),
                "workspace_id": str(connection.workspace_id),
                "chat_provider_connection_id": str(connection.id),
                "chat_provider_event_id": text_message.event_id,
            },
        )
    else:
        if processed:
            response.processed += 1
        else:
            response.duplicates += 1
    return response


def whatsapp_local_payload_items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    messages = payload.get("messages")
    if isinstance(messages, list):
        return [item for item in messages if isinstance(item, dict)]
    message = payload.get("message")
    if isinstance(message, dict):
        return [message]
    return [payload]


async def handle_whatsapp_local_webhook(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    body: bytes,
    secret_header: str | None,
    session_factory: AgentSessionFactory | None = None,
) -> ChatProviderWebhookResponse:
    connection = await active_connection(
        session,
        connection_id,
        provider=PROVIDER_WHATSAPP_LOCAL,
    )
    await validate_webhook_secret(session, connection, secret_header)
    payload = decode_webhook_body(body, provider_name="WhatsApp local")

    response = ChatProviderWebhookResponse()
    for item in whatsapp_local_payload_items(payload):
        text_message = whatsapp_local.text_message(item)
        if text_message is not None:
            response.received += 1
            try:
                processed = await process_provider_text_message(
                    session,
                    connection,
                    provider_message_from_whatsapp_local(text_message),
                    session_factory=session_factory,
                )
            except Exception:
                response.failed += 1
                logger.exception(
                    "Failed to process WhatsApp local chat provider message.",
                    extra={
                        "organization_id": str(connection.organization_id),
                        "workspace_id": str(connection.workspace_id),
                        "chat_provider_connection_id": str(connection.id),
                        "chat_provider_event_id": text_message.event_id,
                    },
                )
            else:
                if processed:
                    response.processed += 1
                else:
                    response.duplicates += 1
            continue

        unsupported = whatsapp_local.unsupported_message(item)
        if unsupported is not None:
            response.received += 1
            handled = await record_unsupported_provider_message(
                session,
                connection,
                provider_unsupported_from_whatsapp_local(unsupported),
            )
            if handled:
                response.ignored += 1
            else:
                response.duplicates += 1
    return response


async def record_unsupported_provider_message(
    session: AsyncSession,
    connection: ChatProviderConnection,
    message: ProviderUnsupportedMessage,
) -> bool:
    if await repository.get_event_by_external_id(
        session,
        connection_id=connection.id,
        external_event_id=message.event_id,
    ):
        return False
    event = ChatProviderEvent(
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        provider=connection.provider,
        external_event_id=message.event_id,
        direction="inbound",
        event_type=f"message.{message.message_type}",
        status="ignored",
        payload={connection.provider: message.raw},
        processed_at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()
    return True


async def process_provider_text_message(
    session: AsyncSession,
    connection: ChatProviderConnection,
    message: ProviderTextMessage,
    *,
    session_factory: AgentSessionFactory | None = None,
) -> bool:
    existing = await repository.get_event_by_external_id(
        session,
        connection_id=connection.id,
        external_event_id=message.event_id,
    )
    if existing is not None:
        return False
    event = ChatProviderEvent(
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        provider=connection.provider,
        external_event_id=message.event_id,
        direction="inbound",
        event_type="message.text",
        status="processing",
        payload={connection.provider: message.raw},
    )
    session.add(event)
    await session.flush()
    try:
        if not sender_allowed(connection, message):
            event.status = "ignored"
            event.error = f"{provider_display_name(connection.provider)} sender is not allowed"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return True
        actor = await provider_actor(session, connection)
        thread, conversation_id, agent_id = await provider_thread_conversation(
            session,
            connection,
            actor,
            message,
        )
        event.thread_id = thread.id
        event.conversation_id = conversation_id
        thread.last_external_message_id = message.event_id
        await session.flush()
        stream = await agent_service.stream_agent_chat(
            session,
            actor,
            connection.organization_id,
            agent_id,
            AgentChatRequest(
                id=str(conversation_id),
                messages=[
                    AgentChatMessage(
                        role="user",
                        parts=text_parts(message.text),
                    )
                ],
            ),
            workspace_id=connection.workspace_id,
            session_factory=session_factory,
        )
        await session.commit()
        async for _chunk in stream:
            pass
        reply_text = await latest_assistant_text(session, conversation_id)
        if not reply_text:
            reply_text = PROVIDER_ASSISTANT_EMPTY_REPLY
        outbound_payload = await send_provider_text_message(
            session,
            connection,
            external_thread_id=message.external_thread_id,
            text=reply_text,
            reply_to_message_id=message.event_id,
        )
        outbound_message_id = provider_response_message_id(connection, outbound_payload)
        outbound_event = ChatProviderEvent(
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            thread_id=thread.id,
            conversation_id=conversation_id,
            provider=connection.provider,
            external_event_id=outbound_message_id or f"outbound:{message.event_id}",
            direction="outbound",
            event_type="message.text",
            status="sent",
            payload={connection.provider: outbound_payload},
            processed_at=datetime.now(UTC),
        )
        session.add(outbound_event)
        event.status = "processed"
        event.processed_at = datetime.now(UTC)
        await session.flush()
    except Exception as exc:
        event.status = "failed"
        event.error = str(exc)
        event.processed_at = datetime.now(UTC)
        await session.flush()
        raise
    return True


async def provider_actor(session: AsyncSession, connection: ChatProviderConnection) -> User:
    if connection.created_by_id is None:
        raise InvalidChatProviderConnectionError("chat provider connection has no run actor")
    user = await get_user_by_id(session, connection.created_by_id)
    if user is None or not user.is_active:
        raise InvalidChatProviderConnectionError("chat provider connection actor is inactive")
    return user


async def provider_thread_conversation(
    session: AsyncSession,
    connection: ChatProviderConnection,
    actor: User,
    message: ProviderTextMessage,
) -> tuple[ChatProviderThread, uuid.UUID, uuid.UUID]:
    thread = await repository.get_thread(
        session,
        connection_id=connection.id,
        external_thread_id=message.external_thread_id,
    )
    conversation = None
    if thread is not None and thread.conversation_id is not None:
        conversation = await agent_repository.get_workspace_conversation(
            session,
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            conversation_id=thread.conversation_id,
        )
    if thread is None or conversation is None:
        quick_start = await agent_service.quick_start_workspace_agent(
            session,
            actor,
            connection.organization_id,
            connection.workspace_id,
        )
        conversation_id = quick_start.conversation.id
        agent_id = quick_start.agent.id
        conversation = await agent_repository.get_workspace_conversation(
            session,
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            conversation_id=conversation_id,
        )
        if conversation is not None:
            conversation.title = provider_conversation_title(connection, message)
        if thread is None:
            thread = ChatProviderThread(
                organization_id=connection.organization_id,
                workspace_id=connection.workspace_id,
                connection_id=connection.id,
                conversation_id=conversation_id,
                external_thread_id=message.external_thread_id,
                external_user_id=message.external_user_id,
                external_user_display_name=message.external_user_display_name,
                provider_metadata={"provider": connection.provider},
            )
            session.add(thread)
            await session.flush()
            await session.refresh(thread)
        else:
            thread.conversation_id = conversation_id
    else:
        conversation_id = conversation.id
        agent_id = conversation.agent_id
    thread.external_user_id = message.external_user_id
    if message.external_user_display_name:
        thread.external_user_display_name = message.external_user_display_name
    await session.flush()
    return thread, conversation_id, agent_id


def provider_conversation_title(
    connection: ChatProviderConnection,
    message: ProviderTextMessage,
) -> str:
    source = (
        connection.display_name
        or connection.name
        or provider_display_name(connection.provider)
    )
    sender = message.external_user_display_name or message.external_user_id
    return f"{source}: {sender}"[:200]


def provider_display_name(provider: str) -> str:
    if provider == PROVIDER_TELEGRAM:
        return "Telegram"
    if provider == PROVIDER_WHATSAPP_LOCAL:
        return "WhatsApp"
    return "Chat provider"


async def latest_assistant_text(session: AsyncSession, conversation_id: uuid.UUID) -> str:
    messages = await agent_repository.list_conversation_messages(
        session,
        conversation_id=conversation_id,
    )
    for message in reversed(messages):
        if message.role == "assistant":
            return message.content.strip()
    return ""


async def send_provider_text_message(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *,
    external_thread_id: str,
    text: str,
    reply_to_message_id: str = "",
) -> dict[str, Any]:
    if connection.provider == PROVIDER_TELEGRAM:
        return await send_telegram_text_message(
            session,
            connection,
            chat_id=external_thread_id,
            text=text,
        )
    if connection.provider == PROVIDER_WHATSAPP_LOCAL:
        return await send_whatsapp_local_text_message(
            session,
            connection,
            chat_id=external_thread_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
        )
    raise ChatProviderDeliveryError("unsupported chat provider")


def provider_response_message_id(
    connection: ChatProviderConnection,
    payload: dict[str, Any],
) -> str:
    if connection.provider == PROVIDER_TELEGRAM:
        return telegram.response_message_id(payload)
    if connection.provider == PROVIDER_WHATSAPP_LOCAL:
        return whatsapp_local.response_message_id(payload)
    return ""


async def send_telegram_text_message(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *,
    chat_id: str,
    text: str,
) -> dict[str, Any]:
    bot_token_secret_handle_id = await connection_secret_handle_id(
        session,
        connection,
        SECRET_BOT_TOKEN,
        SECRET_ACCESS_TOKEN,
    )
    if bot_token_secret_handle_id is None:
        raise ChatProviderDeliveryError("Telegram access token is not configured")
    access_token = await resolve_secret(
        session,
        connection.organization_id,
        bot_token_secret_handle_id,
        workspace_id=connection.workspace_id,
    )
    endpoint = telegram.send_message_endpoint(access_token.value)
    payload = telegram.text_message_payload(chat_id=chat_id, text=text)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(endpoint, json=payload)
    response_payload = response_json(response)
    if response.status_code >= 400:
        raise ChatProviderDeliveryError(
            f"Telegram message delivery failed with HTTP {response.status_code}"
        )
    return response_payload


async def send_whatsapp_local_text_message(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *,
    chat_id: str,
    text: str,
    reply_to_message_id: str = "",
) -> dict[str, Any]:
    config = WhatsAppLocalProviderConfig.model_validate(connection.config or {})
    if not config.outbound_webhook_url:
        raise ChatProviderDeliveryError("WhatsApp local outbound webhook URL is not configured")
    secret_handle_id = await connection_secret_handle_id(
        session,
        connection,
        SECRET_OUTBOUND_SECRET,
        SECRET_WEBHOOK_SECRET,
    )
    if secret_handle_id is None:
        raise ChatProviderDeliveryError("WhatsApp local outbound secret is not configured")
    secret = await resolve_secret(
        session,
        connection.organization_id,
        secret_handle_id,
        workspace_id=connection.workspace_id,
    )
    payload = whatsapp_local.outbound_text_payload(
        connection_id=str(connection.id),
        chat_id=chat_id,
        text=text,
        reply_to_message_id=reply_to_message_id,
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            config.outbound_webhook_url,
            headers={"X-Wardn-Chat-Provider-Secret": secret.value},
            json=payload,
        )
    response_payload = response_json(response)
    if response.status_code >= 400:
        raise ChatProviderDeliveryError(
            f"WhatsApp local message delivery failed with HTTP {response.status_code}"
        )
    return response_payload


def response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"body": response.text}
    if isinstance(payload, dict):
        return payload
    return {"response": payload}
