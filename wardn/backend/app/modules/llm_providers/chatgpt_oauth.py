import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.modules.llm_providers.exceptions import InvalidLLMProviderCredentialAuthError

CHATGPT_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CHATGPT_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_OAUTH_SCOPE = "openid profile email offline_access"
CHATGPT_OAUTH_TOKEN_TIMEOUT_SECONDS = 30.0
CHATGPT_DEVICE_AUTH_USERCODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
CHATGPT_DEVICE_AUTH_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
CHATGPT_DEVICE_AUTH_VERIFICATION_URL = "https://auth.openai.com/codex/device"
CHATGPT_DEVICE_AUTH_CALLBACK_URL = "https://auth.openai.com/deviceauth/callback"
CHATGPT_DEVICE_AUTH_USER_AGENT = "wardn-chatgpt-auth/1.0"
OPENAI_CODEX_AUTH_CLAIM = "https://api.openai.com/auth"
OPENAI_CODEX_PROFILE_CLAIM = "https://api.openai.com/profile"

@dataclass(frozen=True)
class ChatGPTDeviceAuthorization:
    authorization_code: str
    code_verifier: str

@dataclass(frozen=True)
class ChatGPTDeviceCode:
    device_auth_id: str
    user_code: str
    verification_url: str
    interval_seconds: int = 5

def base64url_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

def generate_pkce_pair() -> tuple[str, str]:
    verifier = base64url_bytes(secrets.token_bytes(32))
    challenge = base64url_bytes(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge

def generate_oauth_state() -> str:
    return base64url_bytes(secrets.token_bytes(32))

def utc_now() -> datetime:
    return datetime.now(UTC)

def build_chatgpt_authorization_url(
    *,
    state: str,
    code_challenge: str,
    redirect_uri: str,
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CHATGPT_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": CHATGPT_OAUTH_SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "wardn",
        }
    )
    return f"{CHATGPT_OAUTH_AUTHORIZE_URL}?{query}"

def decode_jwt_payload(token: str) -> dict[str, Any]:
    payload = token.split(".")[1] if "." in token else ""
    if not payload:
        return {}
    padded = payload + ("=" * (-len(payload) % 4))
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        parsed = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

def read_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

def optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None

def chatgpt_oauth_metadata(access_token: str) -> dict[str, Any]:
    payload = decode_jwt_payload(access_token)
    auth = read_record(payload.get(OPENAI_CODEX_AUTH_CLAIM))
    profile = read_record(payload.get(OPENAI_CODEX_PROFILE_CLAIM))
    metadata = {
        "accountId": optional_string(auth.get("chatgpt_account_id")),
        "chatgptPlanType": optional_string(auth.get("chatgpt_plan_type")),
        "email": optional_string(profile.get("email")),
        "subject": optional_string(payload.get("sub")),
    }
    return {key: value for key, value in metadata.items() if value}

def expires_at_from_seconds(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return utc_now() + timedelta(seconds=seconds)

async def exchange_chatgpt_oauth_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=CHATGPT_OAUTH_TOKEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                CHATGPT_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": CHATGPT_OAUTH_CLIENT_ID,
                    "code": code,
                    "code_verifier": code_verifier,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth token exchange failed"
        ) from exc
    if not response.is_success:
        raise InvalidLLMProviderCredentialAuthError(
            f"ChatGPT OAuth token exchange failed with HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth token response is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth token response is invalid")
    if not isinstance(payload.get("access_token"), str) or not isinstance(
        payload.get("refresh_token"), str
    ):
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth token response did not include access and refresh tokens"
        )
    return payload

def chatgpt_device_auth_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": CHATGPT_DEVICE_AUTH_USER_AGENT,
    }

def positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback

async def request_chatgpt_device_code() -> ChatGPTDeviceCode:
    try:
        async with httpx.AsyncClient(timeout=CHATGPT_OAUTH_TOKEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                CHATGPT_DEVICE_AUTH_USERCODE_URL,
                json={"client_id": CHATGPT_OAUTH_CLIENT_ID},
                headers=chatgpt_device_auth_headers(),
            )
    except httpx.HTTPError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization could not reach OpenAI"
        ) from exc
    if not response.is_success:
        raise InvalidLLMProviderCredentialAuthError(
            f"ChatGPT device authorization failed with HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization response is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization response is invalid"
        )
    device_auth_id = payload.get("device_auth_id")
    user_code = payload.get("user_code") or payload.get("usercode")
    if not isinstance(device_auth_id, str) or not device_auth_id.strip():
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization response did not include a device id"
        )
    if not isinstance(user_code, str) or not user_code.strip():
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization response did not include a user code"
        )
    return ChatGPTDeviceCode(
        device_auth_id=device_auth_id.strip(),
        user_code=user_code.strip(),
        verification_url=CHATGPT_DEVICE_AUTH_VERIFICATION_URL,
        interval_seconds=positive_int(payload.get("interval"), 5),
    )

async def poll_chatgpt_device_authorization(
    device_code: ChatGPTDeviceCode,
) -> ChatGPTDeviceAuthorization | None:
    try:
        async with httpx.AsyncClient(timeout=CHATGPT_OAUTH_TOKEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                CHATGPT_DEVICE_AUTH_TOKEN_URL,
                json={
                    "device_auth_id": device_code.device_auth_id,
                    "user_code": device_code.user_code,
                },
                headers=chatgpt_device_auth_headers(),
            )
    except httpx.HTTPError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization polling could not reach OpenAI"
        ) from exc
    if response.status_code in {403, 404, 429}:
        return None
    if not response.is_success:
        raise InvalidLLMProviderCredentialAuthError(
            f"ChatGPT device authorization polling failed with HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization polling response is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT device authorization polling response is invalid"
        )
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        normalized_error = error.strip().casefold()
        if normalized_error in {"authorization_pending", "pending", "slow_down"}:
            return None
        if "expired" in normalized_error:
            raise InvalidLLMProviderCredentialAuthError("ChatGPT device authorization expired")
        raise InvalidLLMProviderCredentialAuthError(error.strip())
    authorization_code = payload.get("authorization_code")
    code_verifier = payload.get("code_verifier")
    if not isinstance(authorization_code, str) or not authorization_code.strip():
        return None
    if not isinstance(code_verifier, str) or not code_verifier.strip():
        return None
    return ChatGPTDeviceAuthorization(
        authorization_code=authorization_code.strip(),
        code_verifier=code_verifier.strip(),
    )

async def refresh_chatgpt_oauth_token(refresh_token: str) -> dict[str, Any]:
    if not refresh_token.strip():
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth refresh token is missing")
    try:
        async with httpx.AsyncClient(timeout=CHATGPT_OAUTH_TOKEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                CHATGPT_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": CHATGPT_OAUTH_CLIENT_ID,
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth token refresh could not reach OpenAI"
        ) from exc
    if response.status_code in {400, 401, 403}:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth refresh token was rejected; reconnect the credential"
        )
    if not response.is_success:
        raise InvalidLLMProviderCredentialAuthError(
            f"ChatGPT OAuth token refresh failed with HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth refresh response is invalid"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth refresh response did not include an access token"
        )
    return payload
