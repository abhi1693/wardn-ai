from app.modules.chat_providers import slack


def test_slack_app_mention_extracts_text_and_strips_bot_mention() -> None:
    payload = {
        "team_id": "T123",
        "event_id": "Ev123",
        "type": "event_callback",
        "event": {
            "type": "app_mention",
            "channel": "C123",
            "user": "U234",
            "text": "<@U999> check prod",
            "ts": "1700000000.000100",
            "event_ts": "1700000000.000100",
        },
    }

    message = slack.text_message(payload, bot_user_id="U999")

    assert message is not None
    assert message.event_id == "Ev123"
    assert message.team_id == "T123"
    assert message.channel_id == "C123"
    assert message.thread_ts == "1700000000.000100"
    assert message.user_id == "U234"
    assert message.text == "check prod"
    assert slack.external_thread_id(
        team_id=message.team_id,
        channel_id=message.channel_id,
        thread_ts=message.thread_ts,
    ) == "T123:C123:1700000000.000100"


def test_slack_dm_extracts_threaded_text_message() -> None:
    payload = {
        "team_id": "T123",
        "event_id": "Ev124",
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "D123",
            "channel_type": "im",
            "user": "U234",
            "text": "continue",
            "thread_ts": "1700000000.000100",
            "ts": "1700000001.000200",
        },
    }

    message = slack.text_message(payload, bot_user_id="U999")

    assert message is not None
    assert message.thread_ts == "1700000000.000100"
    assert message.message_ts == "1700000001.000200"
    assert message.text == "continue"


def test_slack_dm_without_channel_type_extracts_text_message() -> None:
    payload = {
        "team_id": "T123",
        "event_id": "Ev127",
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "D123",
            "user": "U234",
            "text": "hi",
            "ts": "1700000001.000200",
        },
    }

    message = slack.text_message(payload, bot_user_id="U999")

    assert message is not None
    assert message.channel_id == "D123"
    assert message.thread_ts == "1700000001.000200"
    assert message.message_ts == "1700000001.000200"
    assert message.text == "hi"


def test_slack_channel_message_requires_known_thread() -> None:
    payload = {
        "team_id": "T123",
        "event_id": "Ev125",
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C123",
            "channel_type": "channel",
            "user": "U234",
            "text": "ordinary channel chatter",
            "ts": "1700000000.000100",
        },
    }

    assert slack.text_message(payload, bot_user_id="U999") is None


def test_slack_channel_thread_reply_requires_known_thread() -> None:
    payload = {
        "team_id": "T123",
        "event_id": "Ev126",
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C123",
            "channel_type": "channel",
            "user": "U234",
            "text": "thread follow-up",
            "thread_ts": "1700000000.000100",
            "ts": "1700000001.000200",
        },
    }
    thread_id = "T123:C123:1700000000.000100"

    assert slack.text_message(payload, bot_user_id="U999") is None
    message = slack.text_message(payload, bot_user_id="U999", known_thread_ids={thread_id})

    assert message is not None
    assert message.thread_ts == "1700000000.000100"
    assert message.message_ts == "1700000001.000200"
    assert message.text == "thread follow-up"


def test_slack_parser_ignores_bot_events() -> None:
    payload = {
        "team_id": "T123",
        "event_id": "Ev125",
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C123",
            "bot_id": "B123",
            "text": "bot echo",
            "ts": "1700000000.000100",
        },
    }

    assert slack.text_message(payload, bot_user_id="U999") is None
    assert slack.unsupported_message(payload, bot_user_id="U999") is None


def test_slack_text_payload_uses_thread_and_truncates() -> None:
    payload = slack.text_message_payload(
        channel_id="C123",
        thread_ts="1700000000.000100",
        text="hello",
    )

    assert payload == {
        "channel": "C123",
        "text": "hello",
        "thread_ts": "1700000000.000100",
        "unfurl_links": False,
        "unfurl_media": False,
    }
    assert len(slack.outbound_text_body("x" * 5000)) == slack.SLACK_TEXT_MAX_CHARS


def test_slack_external_thread_id_round_trips() -> None:
    thread_id = slack.external_thread_id(
        team_id="T123",
        channel_id="C123",
        thread_ts="1700000000.000100",
    )

    assert slack.parse_external_thread_id(thread_id) == (
        "T123",
        "C123",
        "1700000000.000100",
    )
