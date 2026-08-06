import json
from uuid import uuid4

import pytest

from app.modules.chat_providers import bridge_worker, service
from app.modules.chat_providers.models import ChatProviderConnection


def make_connection(provider: str) -> ChatProviderConnection:
    return ChatProviderConnection(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        created_by_id=uuid4(),
        provider=provider,
        name="Slack",
        external_id="T123",
        display_name="Slack",
        config={
            "allow_all_senders": True,
            "app_id": "A123",
            "team_id": "T123",
        },
        is_active=True,
    )


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def send(self, data: str) -> None:
        self.sent.append(data)


def test_slack_socket_mode_subscription_uses_connection_team_and_app() -> None:
    connection = make_connection(service.PROVIDER_SLACK)

    subscription = bridge_worker.slack_socket_mode_subscription(connection)

    assert subscription is not None
    assert subscription.connection_id == connection.id
    assert subscription.key == ("T123", "A123")


def test_decode_slack_socket_message_rejects_invalid_payloads() -> None:
    assert bridge_worker.decode_slack_socket_message("not-json") is None
    assert bridge_worker.decode_slack_socket_message("[1]") is None
    assert bridge_worker.decode_slack_socket_message(b"\xff") is None


@pytest.mark.asyncio
async def test_slack_socket_stream_acknowledges_and_processes_events(monkeypatch) -> None:
    subscription = bridge_worker.SlackSocketModeSubscription(
        connection_id=uuid4(),
        team_id="T123",
        app_id="A123",
    )
    event_payload = {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": "Ev123",
        "event": {"type": "app_mention", "channel": "C1", "user": "U1", "text": "hi"},
    }
    websocket = FakeWebSocket(
        [
            json.dumps({"type": "hello"}),
            json.dumps(
                {
                    "type": "events_api",
                    "envelope_id": "env-1",
                    "payload": event_payload,
                }
            ),
            json.dumps({"type": "disconnect", "reason": "refresh_requested"}),
        ]
    )
    processed: list[tuple[object, dict]] = []

    async def open_slack_socket_url(connection_id):
        assert connection_id == subscription.connection_id
        return "wss://example.slack.test/socket"

    def connect(url, **kwargs):
        assert url == "wss://example.slack.test/socket"
        assert kwargs["open_timeout"] == 10
        return websocket

    async def process_slack_socket_mode_event(connection_id, payload):
        processed.append((connection_id, payload))

    monkeypatch.setattr(bridge_worker, "open_slack_socket_url", open_slack_socket_url)
    monkeypatch.setattr(bridge_worker.websockets, "connect", connect)
    monkeypatch.setattr(
        bridge_worker,
        "process_slack_socket_mode_event",
        process_slack_socket_mode_event,
    )

    worker = bridge_worker.SlackSocketModeEventWorker(
        retry_base_seconds=1,
        retry_max_seconds=2,
    )
    await worker._stream_once(subscription)

    assert websocket.sent == [json.dumps({"envelope_id": "env-1"})]
    assert processed == [(subscription.connection_id, event_payload)]
