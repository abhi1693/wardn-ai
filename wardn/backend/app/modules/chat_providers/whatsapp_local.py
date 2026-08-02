from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WhatsAppLocalTextMessage:
    event_id: str
    chat_id: str
    sender_id: str
    sender_display_name: str
    text: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class WhatsAppLocalUnsupportedMessage:
    event_id: str
    chat_id: str
    sender_id: str
    sender_display_name: str
    message_type: str
    raw: dict[str, Any]


def string_field(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def text_message(payload: dict[str, Any]) -> WhatsAppLocalTextMessage | None:
    text = string_field(payload, "text", "body", "messageText", "message_text", "caption")
    if not text:
        return None
    event_id = string_field(payload, "messageId", "message_id", "id")
    chat_id = string_field(
        payload,
        "chatId",
        "chat_id",
        "chatJid",
        "chat_jid",
        "jid",
        "remoteJid",
        "remote_jid",
    )
    sender_id = string_field(
        payload,
        "senderId",
        "sender_id",
        "senderJid",
        "sender_jid",
        "from",
        "participant",
    )
    if not event_id or not chat_id or not sender_id:
        return None
    return WhatsAppLocalTextMessage(
        event_id=event_id,
        chat_id=chat_id,
        sender_id=sender_id,
        sender_display_name=string_field(
            payload,
            "senderDisplayName",
            "sender_display_name",
            "senderName",
            "sender_name",
            "pushName",
            "push_name",
            "name",
        ),
        text=text,
        raw=payload,
    )


def unsupported_message(payload: dict[str, Any]) -> WhatsAppLocalUnsupportedMessage | None:
    if text_message(payload) is not None:
        return None
    event_id = string_field(payload, "messageId", "message_id", "id")
    chat_id = string_field(
        payload,
        "chatId",
        "chat_id",
        "chatJid",
        "chat_jid",
        "jid",
        "remoteJid",
        "remote_jid",
    )
    sender_id = string_field(
        payload,
        "senderId",
        "sender_id",
        "senderJid",
        "sender_jid",
        "from",
        "participant",
    )
    if not event_id or not chat_id or not sender_id:
        return None
    return WhatsAppLocalUnsupportedMessage(
        event_id=event_id,
        chat_id=chat_id,
        sender_id=sender_id,
        sender_display_name=string_field(
            payload,
            "senderDisplayName",
            "sender_display_name",
            "senderName",
            "sender_name",
            "pushName",
            "push_name",
            "name",
        ),
        message_type=string_field(payload, "type", "messageType", "message_type") or "unknown",
        raw=payload,
    )


def jid_without_device(value: str) -> str:
    user, separator, server = value.strip().partition("@")
    if not separator:
        return value.strip()
    base_user = user.split(":", 1)[0]
    return f"{base_user}@{server}"


def is_bridge_self_chat(payload: dict[str, Any]) -> bool:
    if payload.get("is_from_me") is not True and payload.get("isFromMe") is not True:
        return False
    chat_id = string_field(payload, "chatId", "chat_id", "chatJid", "chat_jid", "jid")
    sender_id = string_field(payload, "senderId", "sender_id", "senderJid", "sender_jid")
    return bool(
        chat_id
        and sender_id
        and jid_without_device(chat_id) == jid_without_device(sender_id)
    )


def is_bridge_outbound_echo(payload: dict[str, Any]) -> bool:
    is_from_me = payload.get("is_from_me") is True or payload.get("isFromMe") is True
    return bool(is_from_me and not is_bridge_self_chat(payload))


def outbound_text_payload(
    *,
    connection_id: str,
    chat_id: str,
    text: str,
    reply_to_message_id: str = "",
) -> dict[str, Any]:
    payload = {
        "connectionId": connection_id,
        "chatId": chat_id,
        "text": text.strip(),
    }
    if reply_to_message_id:
        payload["replyToMessageId"] = reply_to_message_id
    return payload


def bridge_text_payload(
    *,
    user_id: int | str,
    chat_id: str,
    text: str,
    reply_to_message_id: str = "",
) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "chat_jid": chat_id,
        "text": text.strip(),
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    return payload


def bridge_typing_payload(
    *,
    user_id: int | str,
    chat_id: str,
    typing: bool,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "chat_jid": chat_id,
        "typing": typing,
    }


def response_message_id(payload: dict[str, Any]) -> str:
    direct = string_field(payload, "messageId", "message_id", "id")
    if direct:
        return direct
    message = payload.get("message")
    if isinstance(message, dict):
        return string_field(message, "messageId", "message_id", "id")
    return ""
