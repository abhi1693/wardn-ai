import pytest

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor


def test_cursor_round_trip_is_opaque_and_stable() -> None:
    cursor = encode_cursor("weather", "default", "5b9877a5-ae2a-4c90-b71e-9409df9b251a")

    assert "weather" not in cursor
    assert decode_cursor(cursor, fields=3) == (
        "weather",
        "default",
        "5b9877a5-ae2a-4c90-b71e-9409df9b251a",
    )


@pytest.mark.parametrize("cursor", ["not-base64!", encode_cursor("too", "short")])
def test_invalid_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError, match="invalid cursor"):
        decode_cursor(cursor, fields=3)
