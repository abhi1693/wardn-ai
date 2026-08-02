from types import SimpleNamespace

import pytest

from app.modules.chat_providers import bridge_worker


class FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    async def aiter_lines(self):
        for line in self.lines:
            yield line


@pytest.mark.asyncio
async def test_iter_sse_events_parses_message_data() -> None:
    response = FakeResponse(
        [
            "event: message",
            'data: {"type":"message"',
            'data: ,"payload":{"id":"1"}}',
            "",
        ]
    )

    events = [event async for event in bridge_worker.iter_sse_events(response)]

    assert events == [
        ("message", '{"type":"message"\n,"payload":{"id":"1"}}'),
    ]


def test_decode_bridge_event_data_requires_object() -> None:
    assert bridge_worker.decode_bridge_event_data('{"type":"message"}') == {"type": "message"}
    assert bridge_worker.decode_bridge_event_data('"message"') is None
    assert bridge_worker.decode_bridge_event_data("not-json") is None


def test_retry_delay_uses_bounded_exponential_backoff() -> None:
    assert bridge_worker.retry_delay_seconds(1, base_seconds=2, max_seconds=30) == 2
    assert bridge_worker.retry_delay_seconds(3, base_seconds=2, max_seconds=30) == 8
    assert bridge_worker.retry_delay_seconds(10, base_seconds=2, max_seconds=30) == 30


def test_bridge_subscription_skips_non_numeric_user_id(monkeypatch) -> None:
    monkeypatch.setattr(
        bridge_worker.service,
        "whatsapp_bridge_target",
        lambda connection: SimpleNamespace(base_url="http://bridge:8090", user_id="personal"),
    )

    assert bridge_worker.bridge_subscription(SimpleNamespace(id="connection-1")) is None
