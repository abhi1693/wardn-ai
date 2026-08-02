from app.modules.chat_providers import telegram


def test_telegram_webhook_parser_extracts_text_message() -> None:
    update = {
        "update_id": 123,
        "message": {
            "message_id": 42,
            "from": {
                "id": 987,
                "first_name": "Asha",
                "last_name": "Raman",
                "username": "asha",
            },
            "chat": {"id": 555, "type": "private"},
            "text": "Check workspace health",
        },
    }

    message = telegram.text_message(update)

    assert message is not None
    assert message.event_id == "update:123"
    assert message.chat_id == "555"
    assert message.user_id == "987"
    assert message.user_display_name == "Asha Raman"
    assert message.text == "Check workspace health"


def test_telegram_webhook_parser_extracts_unsupported_message() -> None:
    update = {
        "update_id": 124,
        "message": {
            "message_id": 43,
            "from": {"id": 987},
            "chat": {"id": 555, "type": "private"},
            "photo": [{"file_id": "photo-1"}],
        },
    }

    message = telegram.unsupported_message(update)

    assert message is not None
    assert message.event_id == "update:124"
    assert message.chat_id == "555"
    assert message.user_id == "987"
    assert message.message_type == "photo"


def test_telegram_text_message_payload_uses_bot_api_shape_and_limit() -> None:
    payload = telegram.text_message_payload(chat_id="555", text="hello")

    assert payload == {
        "chat_id": "555",
        "text": "hello",
        "disable_web_page_preview": True,
    }
    assert telegram.send_message_endpoint("token") == (
        "https://api.telegram.org/bottoken/sendMessage"
    )
    assert len(telegram.outbound_text_body("x" * 5000)) == telegram.TELEGRAM_TEXT_MAX_CHARS
