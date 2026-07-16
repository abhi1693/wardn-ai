import json
from datetime import UTC, datetime

import httpx

from app.modules.llm_providers.chatgpt_oauth import decode_jwt_payload, utc_now
from app.modules.llm_providers.exceptions import InvalidLLMProviderCredentialAuthError
from app.modules.llm_providers.schemas import LLMProviderModelRead

SUPPORTED_OAUTH_PROVIDERS = {"chatgpt"}
OPENAI_API_KEY_PROVIDER = "openai"
OPENAI_CHATGPT_PROVIDER = "openai_chatgpt"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
OPENAI_API_KEY_VALIDATION_TIMEOUT_SECONDS = 15.0
OPENAI_CHATGPT_MODEL_IDS = (
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
)

def validate_auth_settings(
    *,
    auth_method: str,
    secret_value: str,
    oauth_provider: str,
) -> None:
    if auth_method == "api_key":
        if not secret_value:
            raise InvalidLLMProviderCredentialAuthError(
                "secret is required for api_key credentials"
            )
        return
    if auth_method == "oauth":
        if oauth_provider not in SUPPORTED_OAUTH_PROVIDERS:
            supported = ", ".join(sorted(SUPPORTED_OAUTH_PROVIDERS))
            raise InvalidLLMProviderCredentialAuthError(
                f"oauthProvider must be one of: {supported}"
            )
        return
    raise InvalidLLMProviderCredentialAuthError("invalid credential auth method")

async def validate_openai_api_key(secret_value: str) -> None:
    try:
        async with httpx.AsyncClient(
            timeout=OPENAI_API_KEY_VALIDATION_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(
                OPENAI_MODELS_URL,
                headers={"Authorization": f"Bearer {secret_value}"},
            )
    except httpx.HTTPError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "OpenAI API key validation could not reach OpenAI"
        ) from exc

    if response.status_code in {401, 403}:
        raise InvalidLLMProviderCredentialAuthError("OpenAI API key was rejected")
    if not response.is_success:
        raise InvalidLLMProviderCredentialAuthError(
            f"OpenAI API key validation failed with HTTP {response.status_code}"
        )

async def fetch_openai_models(bearer_token: str) -> list[LLMProviderModelRead]:
    try:
        async with httpx.AsyncClient(
            timeout=OPENAI_API_KEY_VALIDATION_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(
                OPENAI_MODELS_URL,
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
    except httpx.HTTPError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "OpenAI model discovery could not reach OpenAI"
        ) from exc

    if response.status_code in {401, 403}:
        raise InvalidLLMProviderCredentialAuthError("OpenAI credential was rejected")
    if not response.is_success:
        raise InvalidLLMProviderCredentialAuthError(
            f"OpenAI model discovery failed with HTTP {response.status_code}"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise InvalidLLMProviderCredentialAuthError(
            "OpenAI model discovery response is invalid"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise InvalidLLMProviderCredentialAuthError(
            "OpenAI model discovery response is invalid"
        )

    models = []
    seen: set[str] = set()
    for entry in payload["data"]:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip() or model_id in seen:
            continue
        seen.add(model_id)
        models.append(LLMProviderModelRead(id=model_id, name=model_id))
    return sorted(models, key=lambda model: model.id)

def openai_chatgpt_models() -> list[LLMProviderModelRead]:
    return [
        LLMProviderModelRead(id=model_id, name=model_id)
        for model_id in OPENAI_CHATGPT_MODEL_IDS
    ]

def validate_chatgpt_oauth_credential(
    *,
    oauth_access_token: str,
    oauth_refresh_token: str,
    oauth_expires_at: datetime | None,
) -> None:
    if not oauth_access_token or not oauth_refresh_token:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth credentials require access and refresh tokens"
        )
    if oauth_expires_at is not None and oauth_expires_at <= utc_now():
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth access token is expired")

    payload = decode_jwt_payload(oauth_access_token)
    expires_at = payload.get("exp")
    if isinstance(expires_at, int) and datetime.fromtimestamp(expires_at, UTC) <= utc_now():
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth access token is expired")
