import base64
import json
from collections.abc import Sequence

from pydantic import Field

from app.core.schemas import APIModel


class InvalidCursorError(ValueError):
    pass


class CursorPageMetadata(APIModel):
    count: int = Field(ge=0)
    next_cursor: str = ""


def encode_cursor(*values: str) -> str:
    payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, *, fields: int) -> tuple[str, ...] | None:
    if not cursor:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        values = json.loads(payload)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise InvalidCursorError("invalid cursor")
    if len(values) != fields or not all(isinstance(value, str) for value in values):
        raise InvalidCursorError("invalid cursor")
    return tuple(values)
