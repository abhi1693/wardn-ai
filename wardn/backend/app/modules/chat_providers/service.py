import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.errors import is_constraint_violation
from app.modules.agents import repository as agent_repository
from app.modules.agents import service as agent_service
from app.modules.agents.approval_links import agent_tool_approval_url
from app.modules.agents.conversations import AgentSessionFactory
from app.modules.agents.mappers import text_parts
from app.modules.agents.models import AgentToolApproval, ConversationMessage
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
    ChatProviderKnownIdentityRead,
    ChatProviderPairingStatusResponse,
    ChatProviderWebhookResponse,
    TelegramProviderConfig,
    WhatsAppLocalProviderConfig,
)
from app.modules.organizations.service import require_workspace_admin
from app.modules.secrets.managed import (
    activate_managed_secret,
    delete_managed_secret_handles,
    owner_managed_secrets,
    queue_managed_secret_cleanup,
)
from app.modules.secrets.schemas import SecretHandleCreate
from app.modules.secrets.service import create_secret_handle, resolve_secret, write_secret_values
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
CHAT_PROVIDER_SECRET_PURPOSE = "chat_provider"
CHAT_PROVIDER_SECRET_OWNER_TYPE = "chat_provider_connection"
CHAT_PROVIDER_DUPLICATE_CONSTRAINTS = {
    "uq_chat_provider_connections_workspace_name",
    "uq_chat_provider_connections_workspace_provider_external",
}
PROVIDER_ASSISTANT_EMPTY_REPLY = (
    "I processed that request, but there was no text response to send back here."
)
PROVIDER_TYPING_REFRESH_SECONDS = 4.0
WHATSAPP_BRIDGE_DELIVERY_ATTEMPTS = 5
WHATSAPP_BRIDGE_DELIVERY_RETRY_BASE_SECONDS = 1.0
WHATSAPP_BRIDGE_DELIVERY_RETRY_MAX_SECONDS = 8.0
WHATSAPP_BRIDGE_STATUS_CONNECTED = {"connected", "open", "ready", "registered", "logged_in"}
WHATSAPP_BRIDGE_STATUS_WAITING = {
    "connecting",
    "pairing",
    "qr",
    "scan",
    "waiting",
    "waiting_for_scan",
}
WHATSAPP_BRIDGE_STATUS_DISCONNECTED = {
    "closed",
    "disconnected",
    "logged_out",
    "logout",
    "not_connected",
    "unpaired",
}
LOOPBACK_BRIDGE_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
WHATSAPP_BRIDGE_RECONNECT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
WHATSAPP_BRIDGE_RECONNECT_TEXT_MARKERS = (
    "connect",
    "disconnected",
    "logged",
    "not connected",
    "not ready",
    "session",
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


@dataclass(frozen=True)
class WhatsAppBridgeTarget:
    base_url: str
    user_id: str


@dataclass(frozen=True)
class ProviderTypingTarget:
    provider: str
    endpoint: str
    active_payload: dict[str, Any]
    idle_payload: dict[str, Any] | None = None


@dataclass
class ProviderTypingHandle:
    target: ProviderTypingTarget
    refresh_task: asyncio.Task[None] | None = None


def provider_config_model(
    provider: str,
) -> type[TelegramProviderConfig] | type[WhatsAppLocalProviderConfig]:
    if provider == PROVIDER_TELEGRAM:
        return TelegramProviderConfig
    if provider == PROVIDER_WHATSAPP_LOCAL:
        return WhatsAppLocalProviderConfig
    raise InvalidChatProviderConnectionError("unsupported chat provider")


def bridge_base_url_host(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").casefold()
    except ValueError:
        return ""


def should_replace_bridge_base_url(value: str) -> bool:
    if not value:
        return True
    return bridge_base_url_host(value) in LOOPBACK_BRIDGE_HOSTS


def default_whatsapp_bridge_base_url(settings: Settings | None = None) -> str:
    configured = (settings or get_settings()).chat_provider_whatsapp_bridge_base_url.strip()
    return configured.rstrip("/")


def normalize_connection_config(
    provider: str,
    config: dict[str, Any] | None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        normalized = provider_config_model(provider).model_validate(config or {}).model_dump(
            by_alias=False
        )
    except ValidationError as exc:
        raise InvalidChatProviderConnectionError("invalid chat provider config") from exc
    if provider == PROVIDER_WHATSAPP_LOCAL:
        default_bridge_url = default_whatsapp_bridge_base_url(settings)
        if default_bridge_url and should_replace_bridge_base_url(
            str(normalized.get("bridge_base_url") or "")
        ):
            normalized["bridge_base_url"] = default_bridge_url
    return normalized


def public_connection_config(connection: ChatProviderConnection) -> dict[str, Any]:
    return normalize_connection_config(connection.provider, dict(connection.config or {}))


def normalized_config(connection: ChatProviderConnection) -> dict[str, Any]:
    return normalize_connection_config(connection.provider, dict(connection.config or {}))


def whatsapp_bridge_target(connection: ChatProviderConnection) -> WhatsAppBridgeTarget | None:
    if connection.provider != PROVIDER_WHATSAPP_LOCAL:
        return None
    config = normalized_config(connection)
    base_url = str(config.get("bridge_base_url") or "").strip().rstrip("/")
    if not base_url:
        return None
    user_id = str(
        config.get("bridge_user_id")
        or config.get("account_name")
        or connection.external_id
        or ""
    ).strip()
    return WhatsAppBridgeTarget(
        base_url=base_url,
        user_id=user_id,
    )


def whatsapp_bridge_user_value(user_id: str) -> int | str:
    return int(user_id) if user_id.isdigit() else user_id


def whatsapp_bridge_url(target: WhatsAppBridgeTarget, path: str) -> str:
    return f"{target.base_url}/{path.lstrip('/')}"


def text_payload_field(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def nested_payload(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def bool_payload_field(payload: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return None


def bridge_status_from_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    status_text = text_payload_field(
        payload,
        "status",
        "state",
        "connection",
        "connectionState",
        "connection_state",
    ).lower()
    session = nested_payload(payload, "session", "account")
    if not status_text and session:
        status_text = text_payload_field(
            session,
            "status",
            "state",
            "connection",
            "connectionState",
            "connection_state",
        ).lower()

    connected = payload.get("connected") is True or session.get("connected") is True
    logged_in = bool_payload_field(
        payload,
        "logged_in",
        "loggedIn",
        "isLoggedIn",
        "authenticated",
    )
    session_logged_in = bool_payload_field(
        session,
        "logged_in",
        "loggedIn",
        "isLoggedIn",
        "authenticated",
    )
    if logged_in is None:
        logged_in = session_logged_in
    phone_number = text_payload_field(
        payload,
        "phoneNumber",
        "phone_number",
        "phone",
        "jid",
        "userJid",
        "user_jid",
    ) or text_payload_field(
        session,
        "phoneNumber",
        "phone_number",
        "phone",
        "jid",
        "userJid",
        "user_jid",
    )

    if logged_in is False and (connected or status_text in WHATSAPP_BRIDGE_STATUS_CONNECTED):
        return (
            "needs_pairing",
            "WhatsApp reached the bridge, but the phone is not linked. "
            "Reset pairing and scan a fresh QR.",
            phone_number,
        )
    if logged_in is True or connected or status_text in WHATSAPP_BRIDGE_STATUS_CONNECTED:
        return "connected", "WhatsApp session is connected.", phone_number
    if status_text in WHATSAPP_BRIDGE_STATUS_WAITING:
        return "waiting_for_scan", "Scan the QR code from WhatsApp Linked Devices.", phone_number
    if status_text in WHATSAPP_BRIDGE_STATUS_DISCONNECTED:
        return "needs_pairing", "WhatsApp session needs pairing.", phone_number
    if not payload:
        return "needs_pairing", "WhatsApp session has not reported status yet.", ""
    return "disconnected", "WhatsApp bridge is reachable but not connected.", phone_number


def qr_payload_from_bridge_data(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    return text_payload_field(
        payload,
        "qr",
        "qrCode",
        "qr_code",
        "code",
        "payload",
        "data",
    )


async def request_whatsapp_bridge_status(
    target: WhatsAppBridgeTarget,
) -> tuple[dict[str, Any], str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            whatsapp_bridge_url(target, "/sessions/status"),
            params={"user_id": whatsapp_bridge_user_value(target.user_id)},
        )
    payload = response_json(response)
    if response.status_code >= 400:
        return payload, f"WhatsApp bridge status failed with HTTP {response.status_code}."
    return payload, ""


async def create_whatsapp_bridge_session(target: WhatsAppBridgeTarget) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            whatsapp_bridge_url(target, "/sessions"),
            json={"user_id": whatsapp_bridge_user_value(target.user_id)},
        )
    if response.status_code >= 400 and response.status_code not in {409}:
        return f"WhatsApp bridge session create failed with HTTP {response.status_code}."
    return ""


async def delete_whatsapp_bridge_session(target: WhatsAppBridgeTarget) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.delete(
            whatsapp_bridge_url(target, "/sessions/delete"),
            params={"user_id": whatsapp_bridge_user_value(target.user_id)},
        )
    if response.status_code >= 400:
        return f"WhatsApp bridge session reset failed with HTTP {response.status_code}."
    return ""


async def request_whatsapp_bridge_qr(target: WhatsAppBridgeTarget) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream(
            "GET",
            whatsapp_bridge_url(target, "/sessions/qr"),
            params={"user_id": whatsapp_bridge_user_value(target.user_id)},
        ) as response:
            if response.status_code >= 400:
                return "", f"WhatsApp bridge QR failed with HTTP {response.status_code}."
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if not line:
                    if data_lines:
                        break
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
                elif not line.startswith("event:") and not line.startswith(":"):
                    data_lines.append(line.strip())
                if data_lines:
                    payload = qr_payload_from_bridge_data("\n".join(data_lines))
                    if payload:
                        return payload, ""
    return "", "WhatsApp bridge did not return a QR code."


def whatsapp_pairing_not_configured(connection: ChatProviderConnection) -> (
    ChatProviderPairingStatusResponse
):
    return ChatProviderPairingStatusResponse(
        ok=False,
        provider=connection.provider,
        status="not_configured",
        message="Configure a WhatsApp bridge URL for this deployment.",
    )


def whatsapp_pairing_unsupported(connection: ChatProviderConnection) -> (
    ChatProviderPairingStatusResponse
):
    return ChatProviderPairingStatusResponse(
        ok=False,
        provider=connection.provider,
        status="unsupported",
        message=f"{provider_display_name(connection.provider)} does not support QR pairing.",
    )


async def whatsapp_pairing_response(
    connection: ChatProviderConnection,
    *,
    refresh_qr: bool = False,
    reset_session: bool = False,
) -> ChatProviderPairingStatusResponse:
    if connection.provider != PROVIDER_WHATSAPP_LOCAL:
        return whatsapp_pairing_unsupported(connection)
    target = whatsapp_bridge_target(connection)
    if target is None:
        return whatsapp_pairing_not_configured(connection)

    qr_payload = ""
    create_message = ""
    if refresh_qr:
        try:
            if reset_session:
                delete_message = await delete_whatsapp_bridge_session(target)
                if delete_message:
                    return ChatProviderPairingStatusResponse(
                        ok=False,
                        provider=connection.provider,
                        status="error",
                        message=delete_message,
                        bridgeBaseUrl=target.base_url,
                        bridgeUserId=target.user_id,
                    )
            create_message = await create_whatsapp_bridge_session(target)
            qr_payload, qr_message = await request_whatsapp_bridge_qr(target)
        except httpx.RequestError as exc:
            return ChatProviderPairingStatusResponse(
                ok=False,
                provider=connection.provider,
                status="error",
                message=f"WhatsApp bridge is unreachable: {exc}",
                bridgeBaseUrl=target.base_url,
                bridgeUserId=target.user_id,
            )
        if qr_message and not create_message:
            create_message = qr_message
        elif reset_session and not create_message and qr_payload:
            create_message = "WhatsApp session was reset. Scan this fresh QR from Linked Devices."

    try:
        raw_status, status_message = await request_whatsapp_bridge_status(target)
    except httpx.RequestError as exc:
        return ChatProviderPairingStatusResponse(
            ok=False,
            provider=connection.provider,
            status="error",
            message=f"WhatsApp bridge is unreachable: {exc}",
            bridgeBaseUrl=target.base_url,
            bridgeUserId=target.user_id,
        )

    status_value, default_message, phone_number = bridge_status_from_payload(raw_status)
    if qr_payload and status_value != "connected":
        status_value = "waiting_for_scan"
    message = create_message or status_message or default_message
    return ChatProviderPairingStatusResponse(
        ok=status_value in {"connected", "waiting_for_scan", "needs_pairing", "disconnected"},
        provider=connection.provider,
        status=status_value,
        message=message,
        bridgeBaseUrl=target.base_url,
        bridgeUserId=target.user_id,
        qrPayload=qr_payload,
        phoneNumber=phone_number,
        rawStatus=raw_status,
    )


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


def supported_secret_keys(provider: str) -> set[str]:
    if provider == PROVIDER_TELEGRAM:
        return {
            SECRET_ACCESS_TOKEN,
            SECRET_BOT_TOKEN,
            SECRET_SIGNING_SECRET,
            SECRET_WEBHOOK_SECRET,
        }
    if provider == PROVIDER_WHATSAPP_LOCAL:
        return {
            SECRET_OUTBOUND_SECRET,
            SECRET_WEBHOOK_SECRET,
        }
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


def secret_purpose_label(purpose: str) -> str:
    return " ".join(item.capitalize() for item in purpose.split("_") if item)


def chat_provider_secret_path(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    provider: str,
    connection_id: uuid.UUID,
) -> str:
    return (
        f"wardn/orgs/{organization_id}/workspaces/{workspace_id}"
        f"/chat-providers/{provider}/{connection_id}"
    )


def chat_provider_secret_display_name(
    *,
    connection_name: str,
    purpose: str,
    connection_id: uuid.UUID,
) -> str:
    label = secret_purpose_label(purpose)
    suffix = str(connection_id)[:8]
    return f"{connection_name} {label} ({suffix})"[:100]


async def create_secret_handles_for_values(
    session: AsyncSession,
    user: User,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    provider: str,
    connection_id: uuid.UUID,
    connection_name: str,
    secret_store_id: uuid.UUID | None,
    secret_values: dict[str, str],
) -> tuple[dict[str, uuid.UUID], uuid.UUID | None]:
    normalized_values = {
        key.strip().lower(): value
        for key, value in secret_values.items()
        if key.strip() and isinstance(value, str) and value.strip()
    }
    if not normalized_values:
        return {}, None
    if secret_store_id is None:
        raise InvalidChatProviderConnectionError(
            "secretStoreId is required when secretValues are provided"
        )
    unsupported_keys = set(normalized_values) - supported_secret_keys(provider)
    if unsupported_keys:
        raise InvalidChatProviderConnectionError(
            f"unsupported chat provider secrets: {', '.join(sorted(unsupported_keys))}"
        )

    external_ref = chat_provider_secret_path(
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=provider,
        connection_id=connection_id,
    )
    write_result = await write_secret_values(
        session,
        user,
        organization_id,
        secret_store_id,
        workspace_id=workspace_id,
        external_ref=external_ref,
        values=normalized_values,
        purpose=CHAT_PROVIDER_SECRET_PURPOSE,
        owner_type=CHAT_PROVIDER_SECRET_OWNER_TYPE,
        owner_id=connection_id,
    )
    managed_secret_id = getattr(write_result, "managed_secret_id", None)
    handle_ids: dict[str, uuid.UUID] = {}
    for purpose in sorted(normalized_values):
        handle = await create_secret_handle(
            session,
            user,
            organization_id,
            SecretHandleCreate(
                storeId=secret_store_id,
                workspaceId=workspace_id,
                purpose=CHAT_PROVIDER_SECRET_PURPOSE,
                displayName=chat_provider_secret_display_name(
                    connection_name=connection_name,
                    purpose=purpose,
                    connection_id=connection_id,
                ),
                externalRef=external_ref,
                keyName=purpose,
                metadata={
                    "provider": provider,
                    "connectionId": str(connection_id),
                    "secretKey": purpose,
                },
            ),
            managed_secret_id=managed_secret_id,
        )
        handle_ids[purpose] = handle.id
    return handle_ids, managed_secret_id


async def connection_response(
    session: AsyncSession,
    connection: ChatProviderConnection,
) -> ChatProviderConnectionRead:
    known_identities = [
        ChatProviderKnownIdentityRead(
            external_thread_id=thread.external_thread_id,
            external_user_id=thread.external_user_id,
            display_name=thread.external_user_display_name,
            last_seen_at=thread.updated_at,
        )
        for thread in await repository.list_threads_for_connection(
            session,
            connection_id=connection.id,
        )
    ]
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
        known_identities=known_identities,
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
    connection_id = uuid.uuid4()
    secret_value_handle_ids, managed_secret_id = await create_secret_handles_for_values(
        session,
        user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=payload.provider,
        connection_id=connection_id,
        connection_name=payload.name,
        secret_store_id=payload.secret_store_id,
        secret_values=payload.secret_values,
    )
    secret_handle_ids = {
        **normalize_secret_handle_ids(payload.secret_handle_ids),
        **secret_value_handle_ids,
    }
    await validate_secret_handles(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=payload.provider,
        secret_handle_ids=secret_handle_ids,
    )
    connection = ChatProviderConnection(
        id=connection_id,
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
    await activate_managed_secret(session, managed_secret_id)
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
    managed_secrets = await owner_managed_secrets(
        session,
        owner_type=CHAT_PROVIDER_SECRET_OWNER_TYPE,
        owner_id=connection.id,
    )
    managed_secret_ids = {managed_secret.id for managed_secret in managed_secrets}
    await repository.delete_connection_secrets(session, connection_id=connection.id)
    await delete_managed_secret_handles(session, managed_secret_ids)
    await queue_managed_secret_cleanup(session, managed_secret_ids)
    await session.delete(connection)
    await session.flush()


async def workspace_chat_provider_connection_for_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ChatProviderConnection:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    connection = await repository.get_connection(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise ChatProviderConnectionNotFoundError("chat provider connection not found")
    return connection


async def get_workspace_chat_provider_pairing_status(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ChatProviderPairingStatusResponse:
    connection = await workspace_chat_provider_connection_for_admin(
        session,
        user,
        organization_id,
        workspace_id,
        connection_id,
    )
    return await whatsapp_pairing_response(connection)


async def refresh_workspace_chat_provider_pairing_qr(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ChatProviderPairingStatusResponse:
    connection = await workspace_chat_provider_connection_for_admin(
        session,
        user,
        organization_id,
        workspace_id,
        connection_id,
    )
    return await whatsapp_pairing_response(connection, refresh_qr=True)


async def reset_workspace_chat_provider_pairing_qr(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ChatProviderPairingStatusResponse:
    connection = await workspace_chat_provider_connection_for_admin(
        session,
        user,
        organization_id,
        workspace_id,
        connection_id,
    )
    return await whatsapp_pairing_response(connection, refresh_qr=True, reset_session=True)


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
    bridge_payload = payload.get("payload")
    if isinstance(bridge_payload, dict):
        return [bridge_payload]
    messages = payload.get("messages")
    if isinstance(messages, list):
        return [item for item in messages if isinstance(item, dict)]
    message = payload.get("message")
    if isinstance(message, dict):
        return [message]
    return [payload]


async def process_whatsapp_local_payload_items(
    session: AsyncSession,
    connection: ChatProviderConnection,
    items: list[dict[str, Any]],
    *,
    source: str,
    session_factory: AgentSessionFactory | None = None,
) -> ChatProviderWebhookResponse:
    response = ChatProviderWebhookResponse()
    for item in items:
        if source == "bridge" and whatsapp_local.is_bridge_outbound_echo(item):
            response.received += 1
            response.ignored += 1
            continue
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
                    "Failed to process WhatsApp chat provider message.",
                    extra={
                        "organization_id": str(connection.organization_id),
                        "workspace_id": str(connection.workspace_id),
                        "chat_provider_connection_id": str(connection.id),
                        "chat_provider_event_id": text_message.event_id,
                        "chat_provider_source": source,
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
    return await process_whatsapp_local_payload_items(
        session,
        connection,
        whatsapp_local_payload_items(payload),
        source="webhook",
        session_factory=session_factory,
    )


async def handle_whatsapp_local_bridge_event(
    session: AsyncSession,
    connection: ChatProviderConnection,
    payload: dict[str, Any],
    *,
    session_factory: AgentSessionFactory | None = None,
) -> ChatProviderWebhookResponse:
    if connection.provider != PROVIDER_WHATSAPP_LOCAL:
        raise InvalidChatProviderConnectionError("invalid WhatsApp bridge connection")
    if not connection.is_active:
        return ChatProviderWebhookResponse(received=1, ignored=1)
    return await process_whatsapp_local_payload_items(
        session,
        connection,
        whatsapp_local_payload_items(payload),
        source="bridge",
        session_factory=session_factory,
    )


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
    thread = await record_provider_thread_identity(session, connection, message)
    event = ChatProviderEvent(
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        thread_id=thread.id,
        conversation_id=thread.conversation_id,
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


async def record_provider_thread_identity(
    session: AsyncSession,
    connection: ChatProviderConnection,
    message: ProviderTextMessage | ProviderUnsupportedMessage,
) -> ChatProviderThread:
    thread = await repository.get_thread(
        session,
        connection_id=connection.id,
        external_thread_id=message.external_thread_id,
    )
    if thread is None:
        thread = ChatProviderThread(
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            external_thread_id=message.external_thread_id,
            external_user_id=message.external_user_id,
            external_user_display_name=message.external_user_display_name,
            provider_metadata={"provider": connection.provider},
        )
        session.add(thread)
        await session.flush()
        await session.refresh(thread)
    else:
        thread.external_user_id = message.external_user_id
        if message.external_user_display_name:
            thread.external_user_display_name = message.external_user_display_name
    thread.last_external_message_id = message.event_id
    await session.flush()
    return thread


async def build_provider_typing_target(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *,
    external_thread_id: str,
) -> ProviderTypingTarget | None:
    if connection.provider == PROVIDER_TELEGRAM:
        bot_token_secret_handle_id = await connection_secret_handle_id(
            session,
            connection,
            SECRET_BOT_TOKEN,
            SECRET_ACCESS_TOKEN,
        )
        if bot_token_secret_handle_id is None:
            return None
        access_token = await resolve_secret(
            session,
            connection.organization_id,
            bot_token_secret_handle_id,
            workspace_id=connection.workspace_id,
        )
        return ProviderTypingTarget(
            provider=connection.provider,
            endpoint=telegram.send_chat_action_endpoint(access_token.value),
            active_payload=telegram.typing_action_payload(chat_id=external_thread_id),
        )
    if connection.provider == PROVIDER_WHATSAPP_LOCAL:
        target = whatsapp_bridge_target(connection)
        if target is None:
            return None
        user_id = whatsapp_bridge_user_value(target.user_id)
        return ProviderTypingTarget(
            provider=connection.provider,
            endpoint=whatsapp_bridge_url(target, "/messages/typing"),
            active_payload=whatsapp_local.bridge_typing_payload(
                user_id=user_id,
                chat_id=external_thread_id,
                typing=True,
            ),
            idle_payload=whatsapp_local.bridge_typing_payload(
                user_id=user_id,
                chat_id=external_thread_id,
                typing=False,
            ),
        )
    return None


async def send_provider_typing_target(
    target: ProviderTypingTarget,
    *,
    typing: bool,
) -> None:
    payload = target.active_payload if typing else target.idle_payload
    if payload is None:
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(target.endpoint, json=payload)
    if response.status_code >= 400:
        raise ChatProviderDeliveryError(
            f"{provider_display_name(target.provider)} typing indicator failed "
            f"with HTTP {response.status_code}"
        )


async def provider_typing_refresh_loop(target: ProviderTypingTarget) -> None:
    while True:
        await asyncio.sleep(PROVIDER_TYPING_REFRESH_SECONDS)
        try:
            await send_provider_typing_target(target, typing=True)
        except Exception:
            logger.debug(
                "Failed to refresh chat provider typing indicator.",
                extra={"chat_provider": target.provider},
                exc_info=True,
            )


async def start_provider_typing(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *,
    external_thread_id: str,
) -> ProviderTypingHandle | None:
    try:
        target = await build_provider_typing_target(
            session,
            connection,
            external_thread_id=external_thread_id,
        )
        if target is None:
            return None
        await send_provider_typing_target(target, typing=True)
    except Exception:
        logger.debug(
            "Failed to start chat provider typing indicator.",
            extra={
                "chat_provider_connection_id": str(connection.id),
                "chat_provider": connection.provider,
            },
            exc_info=True,
        )
        return None
    return ProviderTypingHandle(
        target=target,
        refresh_task=asyncio.create_task(provider_typing_refresh_loop(target)),
    )


async def stop_provider_typing(handle: ProviderTypingHandle | None) -> None:
    if handle is None:
        return
    if handle.refresh_task is not None:
        handle.refresh_task.cancel()
        try:
            await handle.refresh_task
        except asyncio.CancelledError:
            pass
    try:
        await send_provider_typing_target(handle.target, typing=False)
    except Exception:
        logger.debug(
            "Failed to stop chat provider typing indicator.",
            extra={"chat_provider": handle.target.provider},
            exc_info=True,
        )


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
    typing_handle: ProviderTypingHandle | None = None
    try:
        if not sender_allowed(connection, message):
            thread = await record_provider_thread_identity(session, connection, message)
            event.thread_id = thread.id
            event.conversation_id = thread.conversation_id
            event.status = "ignored"
            event.error = f"{provider_display_name(connection.provider)} sender is not allowed"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return True
        actor = await provider_actor(session, connection)
        command = agent_service.chat_command_from_text(message.text)
        thread, conversation_id, agent_id = await provider_thread_conversation(
            session,
            connection,
            actor,
            message,
            force_new=command == agent_service.CHAT_COMMAND_NEW,
        )
        event.thread_id = thread.id
        event.conversation_id = conversation_id
        thread.last_external_message_id = message.event_id
        await session.flush()
        if command is not None:
            reply_text = await provider_chat_command_reply_text(
                session,
                connection,
                actor,
                command,
                conversation_id,
            )
            outbound_payload = await send_provider_text_message(
                session,
                connection,
                external_thread_id=message.external_thread_id,
                text=reply_text,
                reply_to_message_id=message.event_id,
            )
            outbound_message_id = provider_response_message_id(connection, outbound_payload)
            session.add(
                ChatProviderEvent(
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
            )
            event.status = "processed"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return True
        typing_handle = await start_provider_typing(
            session,
            connection,
            external_thread_id=message.external_thread_id,
        )
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
            trigger_type=agent_run_trigger_type(connection.provider),
        )
        await session.commit()
        async for _chunk in stream:
            pass
        await stop_provider_typing(typing_handle)
        typing_handle = None
        assistant_message = await latest_assistant_message(session, conversation_id)
        if await assistant_message_run_canceled(session, connection, assistant_message):
            event.status = "processed"
            event.processed_at = datetime.now(UTC)
            await session.flush()
            return True
        reply_text = assistant_message.content.strip() if assistant_message is not None else ""
        if not reply_text:
            reply_text = await pending_approval_reply_text(
                session,
                connection,
                conversation_id,
            )
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
            payload={
                connection.provider: outbound_payload,
                **(
                    {"agentRunId": str(assistant_message.agent_run_id)}
                    if assistant_message is not None and assistant_message.agent_run_id is not None
                    else {}
                ),
            },
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
    finally:
        await stop_provider_typing(typing_handle)
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
    *,
    force_new: bool = False,
) -> tuple[ChatProviderThread, uuid.UUID, uuid.UUID]:
    thread = await repository.get_thread(
        session,
        connection_id=connection.id,
        external_thread_id=message.external_thread_id,
    )
    conversation = None
    if not force_new and thread is not None and thread.conversation_id is not None:
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


async def provider_chat_command_reply_text(
    session: AsyncSession,
    connection: ChatProviderConnection,
    actor: User,
    command: str,
    conversation_id: uuid.UUID,
) -> str:
    if command == agent_service.CHAT_COMMAND_NEW:
        return "Started a new chat. Send your next message to begin."
    if command == agent_service.CHAT_COMMAND_COMPACT:
        compacted_message = await agent_service.compact_workspace_conversation(
            session,
            actor,
            connection.organization_id,
            connection.workspace_id,
            conversation_id,
        )
        if compacted_message is None:
            return "There is not enough conversation to compact yet."
        return (
            "Compacted this chat. Future replies will use the compacted context "
            "plus new messages."
        )
    return f"Unknown command: /{command}"


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


def agent_run_trigger_type(provider: str) -> str:
    if provider == PROVIDER_WHATSAPP_LOCAL:
        return "whatsapp"
    return provider


async def latest_assistant_message(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> ConversationMessage | None:
    messages = await agent_repository.list_conversation_messages(
        session,
        conversation_id=conversation_id,
    )
    for message in reversed(messages):
        if message.role == "assistant":
            return message
    return None


async def latest_assistant_text(session: AsyncSession, conversation_id: uuid.UUID) -> str:
    message = await latest_assistant_message(session, conversation_id)
    return message.content.strip() if message is not None else ""


async def assistant_message_run_canceled(
    session: AsyncSession,
    connection: ChatProviderConnection,
    message: ConversationMessage | None,
) -> bool:
    if message is None or message.agent_run_id is None:
        return False
    agent_run = await agent_repository.get_agent_run(
        session,
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_run_id=message.agent_run_id,
    )
    return agent_run is not None and agent_run.status == "canceled"


def approval_reply_text(approval: AgentToolApproval) -> str:
    approval_url = agent_tool_approval_url(
        organization_id=approval.organization_id,
        workspace_id=approval.workspace_id,
        agent_id=approval.agent_id,
        approval_id=approval.id,
    )
    return (
        f"I need approval to run {approval.tool_name}.\n\n"
        "Open this Wardn approval page to approve or deny the action:\n"
        f"{approval_url}"
    )


async def pending_approval_reply_text(
    session: AsyncSession,
    connection: ChatProviderConnection,
    conversation_id: uuid.UUID,
) -> str:
    approval = await agent_repository.latest_pending_tool_approval_by_conversation(
        session,
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        conversation_id=conversation_id,
    )
    return approval_reply_text(approval) if approval is not None else ""


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


def whatsapp_bridge_delivery_retry_delay(attempt: int) -> float:
    return min(
        WHATSAPP_BRIDGE_DELIVERY_RETRY_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
        WHATSAPP_BRIDGE_DELIVERY_RETRY_MAX_SECONDS,
    )


def whatsapp_bridge_delivery_should_retry(
    status_code: int,
    response_payload: dict[str, Any],
) -> bool:
    if status_code in {401, 403}:
        return False
    if status_code in WHATSAPP_BRIDGE_RECONNECT_STATUS_CODES:
        return True
    if status_code not in {400, 404, 422}:
        return False
    payload_text = json.dumps(response_payload, default=str).casefold()
    return any(marker in payload_text for marker in WHATSAPP_BRIDGE_RECONNECT_TEXT_MARKERS)


async def send_whatsapp_bridge_text_message_with_reconnect(
    target: WhatsAppBridgeTarget,
    *,
    secret: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    last_error = "WhatsApp local bridge delivery failed"
    for attempt in range(1, WHATSAPP_BRIDGE_DELIVERY_ATTEMPTS + 1):
        try:
            create_message = await create_whatsapp_bridge_session(target)
            if create_message:
                last_error = create_message
                if "HTTP 4" in create_message:
                    break
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        whatsapp_bridge_url(target, "/messages/send"),
                        headers={"X-Wardn-Chat-Provider-Secret": secret},
                        json=payload,
                    )
                response_payload = response_json(response)
                if response.status_code < 400:
                    return response_payload
                last_error = (
                    f"WhatsApp local bridge delivery failed with HTTP "
                    f"{response.status_code}"
                )
                if not whatsapp_bridge_delivery_should_retry(
                    response.status_code,
                    response_payload,
                ):
                    break
        except httpx.RequestError as exc:
            last_error = f"WhatsApp bridge is unreachable: {exc}"

        if attempt >= WHATSAPP_BRIDGE_DELIVERY_ATTEMPTS:
            break
        delay = whatsapp_bridge_delivery_retry_delay(attempt)
        logger.warning(
            "WhatsApp bridge delivery failed; reconnecting session before retry.",
            extra={
                "chat_provider_bridge_base_url": target.base_url,
                "chat_provider_bridge_user_id": target.user_id,
                "retry_attempt": attempt + 1,
                "retry_delay_seconds": delay,
                "error": last_error,
            },
        )
        await asyncio.sleep(delay)
    raise ChatProviderDeliveryError(last_error)


async def send_whatsapp_local_text_message(
    session: AsyncSession,
    connection: ChatProviderConnection,
    *,
    chat_id: str,
    text: str,
    reply_to_message_id: str = "",
) -> dict[str, Any]:
    config = WhatsAppLocalProviderConfig.model_validate(connection.config or {})
    target = whatsapp_bridge_target(connection)
    if target is None and not config.outbound_webhook_url:
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
    if target is not None:
        payload = whatsapp_local.bridge_text_payload(
            user_id=whatsapp_bridge_user_value(target.user_id),
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
        )
        return await send_whatsapp_bridge_text_message_with_reconnect(
            target,
            secret=secret.value,
            payload=payload,
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
