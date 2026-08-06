from dataclasses import dataclass
from typing import Any

TELEGRAM_TEXT_MAX_CHARS = 4096


@dataclass(frozen=True)
class TelegramTextMessage:
    event_id: str
    chat_id: str
    user_id: str
    user_display_name: str
    text: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class TelegramUnsupportedMessage:
    event_id: str
    chat_id: str
    user_id: str
    message_type: str
    raw: dict[str, Any]


def user_display_name(user: dict[str, Any]) -> str:
    first_name = str(user.get("first_name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    username = str(user.get("username") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    return full_name or username


def telegram_message(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message")
    if isinstance(message, dict):
        return message
    edited = update.get("edited_message")
    if isinstance(edited, dict):
        return edited
    return None


def message_chat_id(message: dict[str, Any]) -> str:
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return ""
    value = chat.get("id")
    return str(value).strip() if value is not None else ""


def message_user(message: dict[str, Any]) -> dict[str, Any]:
    user = message.get("from")
    return user if isinstance(user, dict) else {}


def message_user_id(message: dict[str, Any]) -> str:
    user = message_user(message)
    value = user.get("id")
    return str(value).strip() if value is not None else ""


def message_event_id(update: dict[str, Any], message: dict[str, Any]) -> str:
    update_id = update.get("update_id")
    if update_id is not None:
        return f"update:{update_id}"
    message_id = message.get("message_id")
    chat_id = message_chat_id(message)
    if message_id is not None and chat_id:
        return f"message:{chat_id}:{message_id}"
    return ""


def text_message(update: dict[str, Any]) -> TelegramTextMessage | None:
    message = telegram_message(update)
    if message is None:
        return None
    text = str(message.get("text") or "").strip()
    if not text:
        return None
    event_id = message_event_id(update, message)
    chat_id = message_chat_id(message)
    user_id = message_user_id(message)
    if not event_id or not chat_id or not user_id:
        return None
    return TelegramTextMessage(
        event_id=event_id,
        chat_id=chat_id,
        user_id=user_id,
        user_display_name=user_display_name(message_user(message)),
        text=text,
        raw=message,
    )


def unsupported_message(update: dict[str, Any]) -> TelegramUnsupportedMessage | None:
    message = telegram_message(update)
    if message is None or "text" in message:
        return None
    event_id = message_event_id(update, message)
    chat_id = message_chat_id(message)
    user_id = message_user_id(message)
    if not event_id or not chat_id:
        return None
    known_types = (
        "photo",
        "document",
        "audio",
        "video",
        "voice",
        "sticker",
        "location",
        "contact",
    )
    message_type = next((item for item in known_types if item in message), "unknown")
    return TelegramUnsupportedMessage(
        event_id=event_id,
        chat_id=chat_id,
        user_id=user_id,
        message_type=message_type,
        raw=message,
    )


def send_message_endpoint(bot_token: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}/sendMessage"


def send_chat_action_endpoint(bot_token: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}/sendChatAction"


def edit_message_endpoint(bot_token: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}/editMessageText"


def text_message_payload(*, chat_id: str, text: str) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "text": outbound_text_body(text),
        "disable_web_page_preview": True,
    }


def edit_message_payload(*, chat_id: str, message_id: str, text: str) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": outbound_text_body(text),
        "disable_web_page_preview": True,
    }


def typing_action_payload(*, chat_id: str) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "action": "typing",
    }


def outbound_text_body(text: str) -> str:
    value = text.strip()
    if len(value) <= TELEGRAM_TEXT_MAX_CHARS:
        return value
    suffix = "\n\n[truncated]"
    return value[: TELEGRAM_TEXT_MAX_CHARS - len(suffix)] + suffix


def response_message_id(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if not isinstance(result, dict):
        return ""
    message_id = result.get("message_id")
    chat = result.get("chat")
    chat_id = ""
    if isinstance(chat, dict) and chat.get("id") is not None:
        chat_id = str(chat.get("id")).strip()
    if message_id is None or not chat_id:
        return ""
    return f"message:{chat_id}:{message_id}"
