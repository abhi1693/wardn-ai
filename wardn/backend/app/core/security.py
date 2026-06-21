import hashlib
import hmac
import json
import secrets
import time
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode

from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def generate_api_token() -> tuple[str, str]:
    settings = get_settings()
    key = secrets.token_urlsafe(9)
    secret = secrets.token_urlsafe(32)
    token = f"{settings.api_token_prefix}_{key}.{secret}"
    return key, token


def hash_api_token(token: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.api_token_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_api_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_api_token(token), token_hash)


def extract_api_token_key(token: str) -> str | None:
    settings = get_settings()
    prefix = f"{settings.api_token_prefix}_"
    if not token.startswith(prefix) or "." not in token:
        return None
    key, _ = token.removeprefix(prefix).split(".", 1)
    return key or None


def _base64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def create_session_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "exp": int(time.time()) + settings.session_ttl_seconds,
    }
    payload_data = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_data.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_data}.{_base64url_encode(signature)}"


def verify_session_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    try:
        payload_data, signature_data = token.split(".", 1)
        expected_signature = hmac.new(
            settings.session_secret.encode("utf-8"),
            payload_data.encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied_signature = _base64url_decode(signature_data)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None

        payload = json.loads(_base64url_decode(payload_data))
        if int(payload["exp"]) < int(time.time()):
            return None
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
