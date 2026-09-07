"""Bounded metadata only; raw messages, arguments and results remain in their source stores."""

import json
import re
from typing import Any

from app.modules.agents.mappers import is_sensitive_key, sanitize_run_payload

MAX_EVENT_BYTES = 16_384
HIDDEN_KEYS = {"reasoning", "reasoningsummary", "chainofthought", "scratchpad", "analysis"}
EXTRA_SECRET_KEYS = {"credential", "credentials", "privatekey", "accesskey", "sessionid"}
SECRET_TEXT = (
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\bbasic\s+[a-z0-9+/=]+"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


def normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def redact_data(data: dict[str, Any], sensitive_paths: list[str] | None = None) -> dict:
    sensitive = set(sensitive_paths or [])

    def clean(value: Any, path: str = "", depth: int = 0) -> Any:
        if path in sensitive:
            return "[redacted]"
        if depth > 8:
            return "[omitted: depth limit]"
        if isinstance(value, dict):
            result = {}
            for key, item in list(value.items())[:64]:
                key = str(key)
                normalized = normalized_key(key)
                if normalized in HIDDEN_KEYS:
                    continue
                if is_sensitive_key(key) or normalized in EXTRA_SECRET_KEYS:
                    result[key] = "[redacted]"
                else:
                    result[key] = clean(item, f"{path}.{key}".lstrip("."), depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [clean(item, f"{path}.{i}", depth + 1) for i, item in enumerate(value[:32])]
        if isinstance(value, str):
            # Redact before truncating so partial private-key blocks cannot survive.
            for pattern in SECRET_TEXT:
                value = pattern.sub("[redacted]", value)
            return sanitize_run_payload(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[omitted: unsupported value]"

    result = clean(data)
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_EVENT_BYTES:
        return {"payload_omitted": True, "reason": "metadata size limit"}
    return result
