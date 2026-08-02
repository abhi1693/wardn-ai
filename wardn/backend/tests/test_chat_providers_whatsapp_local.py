from app.modules.chat_providers import whatsapp_local


def test_whatsapp_local_parser_extracts_text_message() -> None:
    payload = {
        "messageId": "wa-inbound-1",
        "chatId": "15551234567@s.whatsapp.net",
        "senderId": "15551234567@s.whatsapp.net",
        "senderDisplayName": "Asha",
        "text": "Check workspace health",
    }

    message = whatsapp_local.text_message(payload)

    assert message is not None
    assert message.event_id == "wa-inbound-1"
    assert message.chat_id == "15551234567@s.whatsapp.net"
    assert message.sender_id == "15551234567@s.whatsapp.net"
    assert message.sender_display_name == "Asha"
    assert message.text == "Check workspace health"


def test_whatsapp_local_parser_extracts_unsupported_message() -> None:
    payload = {
        "messageId": "wa-image-1",
        "chatId": "15551234567@s.whatsapp.net",
        "senderId": "15551234567@s.whatsapp.net",
        "type": "image",
    }

    message = whatsapp_local.unsupported_message(payload)

    assert message is not None
    assert message.event_id == "wa-image-1"
    assert message.message_type == "image"


def test_whatsapp_local_outbound_payload_uses_bridge_contract() -> None:
    payload = whatsapp_local.outbound_text_payload(
        connection_id="connection-1",
        chat_id="15551234567@s.whatsapp.net",
        text=" hello ",
        reply_to_message_id="wa-inbound-1",
    )

    assert payload == {
        "connectionId": "connection-1",
        "chatId": "15551234567@s.whatsapp.net",
        "text": "hello",
        "replyToMessageId": "wa-inbound-1",
    }


def test_whatsapp_local_bridge_payload_uses_wa_meow_contract() -> None:
    payload = whatsapp_local.bridge_text_payload(
        user_id=1,
        chat_id="15551234567@s.whatsapp.net",
        text=" hello ",
        reply_to_message_id="wa-inbound-1",
    )

    assert payload == {
        "user_id": 1,
        "chat_jid": "15551234567@s.whatsapp.net",
        "text": "hello",
        "reply_to_message_id": "wa-inbound-1",
    }
