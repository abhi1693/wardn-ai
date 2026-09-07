"""Concrete request URLs for logs, without credentials or arbitrary query values."""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# Free-text searches, cursors and unknown/authentication parameters stay private.
_QUERY_FIELDS = frozenset({"limit", "offset", "status", "includeDeleted", "version"})
_HOST = re.compile(r"(?:[a-z0-9.-]+|\[[a-f0-9:.]+\])(?::[0-9]+)?\Z", re.IGNORECASE)
_QUERY_VALUE = re.compile(r"[a-zA-Z0-9_.:, -]{0,200}\Z")
_MAX_URL = 4096


def safe_request_url(value: Any) -> str:
    """Allow HTTP request locations only; remain safe for malformed log records."""
    if not isinstance(value, str):
        return "[omitted]"
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"", "http", "https"}:
            return "[redacted-url]"
        authority = parts.netloc.rsplit("@", 1)[-1]  # Never retain URL userinfo.
        if authority and not _HOST.fullmatch(authority):
            return "[redacted-url]"
        path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
        path = re.sub(r"(/invitations/)[^/]+", r"\1[redacted]", path)
        query = urlencode(
            [
                (
                    key[:100],
                    item if key in _QUERY_FIELDS and _QUERY_VALUE.fullmatch(item) else "[redacted]",
                )
                for key, item in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=100)
            ],
            safe="[],:",
        )
        result = urlunsplit((parts.scheme, authority, path, query, ""))
    except (ValueError, UnicodeError):
        # Preserve the path even when an excessive/malformed query cannot be parsed.
        return safe_request_url(value.split("?", 1)[0]) if "?" in value else "[redacted-url]"
    return result if len(result) <= _MAX_URL else result[:_MAX_URL] + "[truncated]"


def request_log_fields(scope: Mapping[str, Any]) -> dict[str, str]:
    """Use the received request, not router templates or untrusted forwarding headers."""
    raw_path = scope.get("raw_path")
    path = (
        quote(raw_path.decode("ascii", "replace"), safe="/%:@!$&'()*+,;=-._~")
        if isinstance(raw_path, bytes)
        else quote(scope.get("path", "/"), safe="/:@!$&'()*+,;=-._~")
    )
    host = next(
        (value.decode("latin-1") for key, value in scope.get("headers", []) if key == b"host"),
        "",
    )
    scheme = scope.get("scheme", "http")
    if not _HOST.fullmatch(host):
        server = scope.get("server")
        if server:
            hostname, port = server
            hostname = f"[{hostname}]" if ":" in hostname else hostname
            host = (
                hostname
                if port in {None, {"http": 80, "https": 443}.get(scheme)}
                else f"{hostname}:{port}"
            )
        else:
            host = ""
    query = scope.get("query_string", b"").decode("utf-8", "replace")
    url = f"{scheme}://{host}{path}" if host else path
    return {
        "method": scope["method"],
        "route": safe_request_url(path),
        "request_url": safe_request_url(url + ("?" + query if query else "")),
    }
