from dataclasses import dataclass
from typing import Any

SLACK_TEXT_MAX_CHARS = 4000


@dataclass(frozen=True)
class SlackTextMessage:
    event_id: str
    team_id: str
    channel_id: str
    thread_ts: str
    message_ts: str
    user_id: str
    user_display_name: str
    text: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class SlackUnsupportedMessage:
    event_id: str
    team_id: str
    channel_id: str
    thread_ts: str
    message_ts: str
    user_id: str
    user_display_name: str
    message_type: str
    raw: dict[str, Any]


def event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event")
    return event if isinstance(event, dict) else {}


def outer_event_id(payload: dict[str, Any], event: dict[str, Any]) -> str:
    event_id = string_field(payload, "event_id")
    if event_id:
        return event_id
    team_id = string_field(payload, "team_id", "team")
    channel_id = string_field(event, "channel")
    message_ts = string_field(event, "event_ts", "ts")
    if team_id and channel_id and message_ts:
        return f"event:{team_id}:{channel_id}:{message_ts}"
    return ""


def string_field(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def event_team_id(payload: dict[str, Any], event: dict[str, Any]) -> str:
    return string_field(event, "team") or string_field(payload, "team_id", "team")


def event_thread_ts(event: dict[str, Any]) -> str:
    return string_field(event, "thread_ts") or string_field(event, "ts", "event_ts")


def event_channel_type(event: dict[str, Any]) -> str:
    return string_field(event, "channel_type").lower()


def external_thread_id(*, team_id: str, channel_id: str, thread_ts: str) -> str:
    return f"{team_id}:{channel_id}:{thread_ts}"


def parse_external_thread_id(value: str) -> tuple[str, str, str]:
    team_id, separator, remainder = value.partition(":")
    channel_id, channel_separator, thread_ts = remainder.partition(":")
    if not separator or not channel_separator or not team_id or not channel_id or not thread_ts:
        return "", "", ""
    return team_id, channel_id, thread_ts


def event_user_id(event: dict[str, Any]) -> str:
    return string_field(event, "user")


def event_display_name(event: dict[str, Any]) -> str:
    return string_field(event, "username", "user_name", "display_name")


def strip_bot_mention(text: str, bot_user_id: str) -> str:
    value = text.strip()
    bot_id = bot_user_id.strip()
    if not bot_id:
        return value
    for mention in (f"<@{bot_id}>", f"<@{bot_id}|"):
        if not value.startswith(mention):
            continue
        if mention.endswith("|"):
            closing = value.find(">")
            if closing >= 0:
                return value[closing + 1 :].strip()
        return value[len(mention) :].strip()
    return value


def is_bot_event(event: dict[str, Any], *, bot_user_id: str = "") -> bool:
    if string_field(event, "bot_id"):
        return True
    if isinstance(event.get("bot_profile"), dict):
        return True
    subtype = string_field(event, "subtype")
    if subtype in {"bot_message", "message_changed", "message_deleted"}:
        return True
    return bool(bot_user_id and event_user_id(event) == bot_user_id)


def event_is_allowed_message_thread(
    event: dict[str, Any],
    *,
    team_id: str,
    channel_id: str,
    known_thread_ids: set[str] | None = None,
) -> bool:
    channel_type = event_channel_type(event)
    if channel_type in {"im", "mpim"} or channel_id.startswith("D"):
        return True
    message_ts = string_field(event, "ts", "event_ts")
    explicit_thread_ts = string_field(event, "thread_ts")
    if not explicit_thread_ts or explicit_thread_ts == message_ts:
        return False
    if known_thread_ids is None:
        return False
    thread_id = external_thread_id(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=explicit_thread_ts,
    )
    return thread_id in known_thread_ids


def text_message(
    payload: dict[str, Any],
    *,
    bot_user_id: str = "",
    known_thread_ids: set[str] | None = None,
) -> SlackTextMessage | None:
    event = event_payload(payload)
    event_type = string_field(event, "type")
    if event_type not in {"app_mention", "message"}:
        return None
    if is_bot_event(event, bot_user_id=bot_user_id):
        return None
    team_id = event_team_id(payload, event)
    channel_id = string_field(event, "channel")
    if event_type == "message" and not event_is_allowed_message_thread(
        event,
        team_id=team_id,
        channel_id=channel_id,
        known_thread_ids=known_thread_ids,
    ):
        return None
    thread_ts = event_thread_ts(event)
    message_ts = string_field(event, "ts", "event_ts")
    user_id = event_user_id(event)
    event_id = outer_event_id(payload, event)
    text = string_field(event, "text")
    if event_type == "app_mention":
        text = strip_bot_mention(text, bot_user_id)
    if not all((event_id, team_id, channel_id, thread_ts, message_ts, user_id, text)):
        return None
    return SlackTextMessage(
        event_id=event_id,
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message_ts=message_ts,
        user_id=user_id,
        user_display_name=event_display_name(event),
        text=text,
        raw=event,
    )


def unsupported_message(
    payload: dict[str, Any],
    *,
    bot_user_id: str = "",
    known_thread_ids: set[str] | None = None,
) -> SlackUnsupportedMessage | None:
    event = event_payload(payload)
    event_type = string_field(event, "type")
    if event_type not in {"app_mention", "message"}:
        return None
    if is_bot_event(event, bot_user_id=bot_user_id):
        return None
    team_id = event_team_id(payload, event)
    channel_id = string_field(event, "channel")
    if event_type == "message" and not event_is_allowed_message_thread(
        event,
        team_id=team_id,
        channel_id=channel_id,
        known_thread_ids=known_thread_ids,
    ):
        return None
    if text_message(
        payload,
        bot_user_id=bot_user_id,
        known_thread_ids=known_thread_ids,
    ) is not None:
        return None
    thread_ts = event_thread_ts(event)
    message_ts = string_field(event, "ts", "event_ts")
    event_id = outer_event_id(payload, event)
    if not all((event_id, team_id, channel_id, thread_ts, message_ts)):
        return None
    message_type = string_field(event, "subtype") or event_type or "unknown"
    return SlackUnsupportedMessage(
        event_id=event_id,
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message_ts=message_ts,
        user_id=event_user_id(event),
        user_display_name=event_display_name(event),
        message_type=message_type,
        raw=event,
    )


def text_message_payload(*, channel_id: str, thread_ts: str, text: str) -> dict[str, Any]:
    return {
        "channel": channel_id,
        "text": outbound_text_body(text),
        "thread_ts": thread_ts,
        "unfurl_links": False,
        "unfurl_media": False,
    }


def outbound_text_body(text: str) -> str:
    value = text.strip()
    if len(value) <= SLACK_TEXT_MAX_CHARS:
        return value
    suffix = "\n\n[truncated]"
    return value[: SLACK_TEXT_MAX_CHARS - len(suffix)] + suffix


def response_message_id(payload: dict[str, Any]) -> str:
    channel_id = string_field(payload, "channel")
    message_ts = string_field(payload, "ts")
    if not channel_id or not message_ts:
        return ""
    return f"message:{channel_id}:{message_ts}"
