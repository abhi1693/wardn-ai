import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits import service as limits_service
from app.modules.llm_providers import repository
from app.modules.llm_providers.exceptions import (
    DuplicateLLMProviderCredentialError,
    InvalidLLMProviderCredentialAuthError,
    InvalidLLMProviderCredentialScopeError,
    LLMProviderCredentialNotFoundError,
)
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.schemas import (
    LLMProviderCredentialCreate,
    LLMProviderCredentialListResponse,
    LLMProviderCredentialRead,
    LLMProviderCredentialUpdate,
    LLMProviderCredentialValidationResponse,
    LLMProviderModelListResponse,
    LLMProviderModelRead,
)
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
)
from app.modules.secrets import repository as secrets_repository
from app.modules.secrets.exceptions import InvalidSecretHandleError, SecretsError
from app.modules.secrets.provider import SecretResolutionContext
from app.modules.secrets.providers.registry import get_secret_provider
from app.modules.secrets.schemas import SecretHandleCreate
from app.modules.secrets.service import create_secret_handle, resolve_secret, write_secret_values
from app.modules.users.models import User

SUPPORTED_OAUTH_PROVIDERS = {"chatgpt"}
OPENAI_API_KEY_PROVIDER = "openai"
OPENAI_CHATGPT_PROVIDER = "openai_chatgpt"
CHATGPT_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CHATGPT_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_OAUTH_SCOPE = "openid profile email offline_access"
CHATGPT_OAUTH_TOKEN_TIMEOUT_SECONDS = 30.0
OPENAI_CODEX_AUTH_CLAIM = "https://api.openai.com/auth"
OPENAI_CODEX_PROFILE_CLAIM = "https://api.openai.com/profile"
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


@dataclass(frozen=True)
class ResolvedLLMCredentialSecrets:
    api_key: str = ""
    oauth_access_token: str = ""
    oauth_refresh_token: str = ""


def normalize_provider(value: str) -> str:
    return value.strip().casefold()


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


def safe_secret_path_component(value: str) -> str:
    component = "".join(
        character.lower() if character.isalnum() else "-"
        for character in value.strip()
    )
    return "-".join(part for part in component.split("-") if part) or "credential"


def llm_secret_path(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    provider: str,
    name: str,
) -> str:
    if workspace_id is not None:
        scope = f"workspaces/{workspace_id}"
    elif user_id is not None:
        scope = f"users/{user_id}"
    else:
        scope = "organization"
    return (
        f"wardn/orgs/{organization_id}/{scope}/llm/{safe_secret_path_component(provider)}/"
        f"{safe_secret_path_component(name)}-{uuid.uuid4()}"
    )


def secret_handle_display_name(name: str, suffix: str) -> str:
    base = normalize_name(name) or "LLM credential"
    value = f"{base} {suffix}"
    if len(value) <= 100:
        return value
    suffix_with_space = f" {suffix}"
    return f"{base[: 100 - len(suffix_with_space)].rstrip()}{suffix_with_space}"


def normalize_oauth_provider(value: str | None) -> str:
    return (value or "").strip().casefold()


def normalize_credential_provider(
    value: str,
    *,
    auth_method: str,
    oauth_provider: str,
) -> str:
    if auth_method == "oauth" and oauth_provider == "chatgpt":
        return OPENAI_CHATGPT_PROVIDER
    return normalize_provider(value)


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


async def get_oauth_secret_handle(
    session: AsyncSession,
    credential: LLMProviderCredential,
    handle_id: uuid.UUID,
) -> tuple[Any, Any]:
    handle = await secrets_repository.get_handle(
        session,
        organization_id=credential.organization_id,
        handle_id=handle_id,
    )
    if handle is None:
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth secret handle was not found")
    store = await secrets_repository.get_store(
        session,
        organization_id=credential.organization_id,
        store_id=handle.store_id,
    )
    if store is None or not store.is_active:
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth secret store is not available")
    if store.workspace_id is not None and store.workspace_id != handle.workspace_id:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth secret handle and store workspaces do not match"
        )
    external_ref = handle.external_ref.strip().strip("/")
    key_name = handle.key_name.strip()
    if not external_ref or not key_name:
        raise InvalidLLMProviderCredentialAuthError("ChatGPT OAuth secret handle is incomplete")
    return handle, store


async def write_oauth_secret_values(
    credential: LLMProviderCredential,
    handle: Any,
    store: Any,
    values: dict[str, str],
) -> None:
    try:
        await get_secret_provider(store.provider).write(
            store,
            handle.external_ref.strip().strip("/"),
            values,
            SecretResolutionContext(
                organization_id=str(credential.organization_id),
                workspace_id=str(handle.workspace_id or credential.workspace_id)
                if handle.workspace_id or credential.workspace_id
                else None,
                purpose=handle.purpose,
            ),
        )
    except (InvalidSecretHandleError, SecretsError) as exc:
        raise InvalidLLMProviderCredentialAuthError(str(exc)) from exc


async def refresh_chatgpt_oauth_credential(
    session: AsyncSession,
    credential: LLMProviderCredential,
    secrets: ResolvedLLMCredentialSecrets,
) -> ResolvedLLMCredentialSecrets:
    if credential.oauth_access_token_secret_handle_id is None:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth access token secret handle is required"
        )
    if credential.oauth_refresh_token_secret_handle_id is None:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth refresh token secret handle is required"
        )
    payload = await refresh_chatgpt_oauth_token(secrets.oauth_refresh_token)
    access_token = payload["access_token"]
    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        refresh_token = secrets.oauth_refresh_token
    token_values = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    access_handle, access_store = await get_oauth_secret_handle(
        session,
        credential,
        credential.oauth_access_token_secret_handle_id,
    )
    refresh_handle, refresh_store = await get_oauth_secret_handle(
        session,
        credential,
        credential.oauth_refresh_token_secret_handle_id,
    )
    access_key = access_handle.key_name.strip()
    refresh_key = refresh_handle.key_name.strip()
    values_by_target: dict[tuple[uuid.UUID, str], dict[str, str]] = {}
    handles_by_target: dict[tuple[uuid.UUID, str], tuple[Any, Any]] = {}
    for handle, store, key_name in (
        (access_handle, access_store, access_key),
        (refresh_handle, refresh_store, refresh_key),
    ):
        value = token_values.get(key_name)
        if not value:
            raise InvalidLLMProviderCredentialAuthError(
                "ChatGPT OAuth token refresh value is missing"
            )
        target = (store.id, handle.external_ref.strip().strip("/"))
        values_by_target.setdefault(target, {})[key_name] = value
        handles_by_target[target] = (handle, store)
    for target, values in values_by_target.items():
        handle, store = handles_by_target[target]
        await write_oauth_secret_values(credential, handle, store, values)
    credential.oauth_expires_at = expires_at_from_seconds(payload.get("expires_in"))
    credential.oauth_metadata = chatgpt_oauth_metadata(access_token)
    if isinstance(payload.get("scope"), str):
        credential.oauth_scopes = payload["scope"].split()
    await session.flush()
    return ResolvedLLMCredentialSecrets(
        oauth_access_token=access_token,
        oauth_refresh_token=refresh_token,
    )


async def replace_chatgpt_oauth_credential_tokens(
    session: AsyncSession,
    credential: LLMProviderCredential,
    token_payload: dict[str, Any],
) -> None:
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth token response did not include an access token"
        )
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth token response did not include a refresh token"
        )
    if credential.oauth_access_token_secret_handle_id is None:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth access token secret handle is required"
        )
    if credential.oauth_refresh_token_secret_handle_id is None:
        raise InvalidLLMProviderCredentialAuthError(
            "ChatGPT OAuth refresh token secret handle is required"
        )
    access_handle, access_store = await get_oauth_secret_handle(
        session,
        credential,
        credential.oauth_access_token_secret_handle_id,
    )
    refresh_handle, refresh_store = await get_oauth_secret_handle(
        session,
        credential,
        credential.oauth_refresh_token_secret_handle_id,
    )
    token_values = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    values_by_target: dict[tuple[uuid.UUID, str], dict[str, str]] = {}
    handles_by_target: dict[tuple[uuid.UUID, str], tuple[Any, Any]] = {}
    for handle, store in ((access_handle, access_store), (refresh_handle, refresh_store)):
        key_name = handle.key_name.strip()
        value = token_values.get(key_name)
        if not value:
            raise InvalidLLMProviderCredentialAuthError(
                "ChatGPT OAuth token response does not match the configured secret handles"
            )
        target = (store.id, handle.external_ref.strip().strip("/"))
        values_by_target.setdefault(target, {})[key_name] = value
        handles_by_target[target] = (handle, store)
    for target, values in values_by_target.items():
        handle, store = handles_by_target[target]
        await write_oauth_secret_values(credential, handle, store, values)
    credential.oauth_expires_at = expires_at_from_seconds(token_payload.get("expires_in"))
    credential.oauth_metadata = chatgpt_oauth_metadata(access_token)
    if isinstance(token_payload.get("scope"), str):
        credential.oauth_scopes = token_payload["scope"].split()
    await session.flush()


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


async def validate_provider_credential(
    *,
    provider: str,
    auth_method: str,
    secret_value: str,
    oauth_provider: str,
    oauth_access_token: str,
    oauth_refresh_token: str,
    oauth_expires_at: datetime | None,
) -> None:
    validate_auth_settings(
        auth_method=auth_method,
        secret_value=secret_value,
        oauth_provider=oauth_provider,
    )

    if provider == OPENAI_API_KEY_PROVIDER and auth_method == "api_key":
        await validate_openai_api_key(secret_value)
        return

    if (
        provider == OPENAI_CHATGPT_PROVIDER
        and auth_method == "oauth"
        and oauth_provider == "chatgpt"
    ):
        validate_chatgpt_oauth_credential(
            oauth_access_token=oauth_access_token,
            oauth_refresh_token=oauth_refresh_token,
            oauth_expires_at=oauth_expires_at,
        )
        return

    raise InvalidLLMProviderCredentialAuthError(
        f"unsupported provider/auth combination: {provider}/{auth_method}"
    )


async def resolve_llm_secret(
    session: AsyncSession,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID | None,
    *,
    workspace_id: uuid.UUID | None,
    label: str,
) -> str:
    if handle_id is None:
        raise InvalidLLMProviderCredentialAuthError(f"{label} secret handle is required")
    try:
        resolved = await resolve_secret(
            session,
            organization_id,
            handle_id,
            workspace_id=workspace_id,
        )
    except SecretsError as exc:
        raise InvalidLLMProviderCredentialAuthError(str(exc)) from exc
    if not resolved.value:
        raise InvalidLLMProviderCredentialAuthError(f"{label} secret handle resolved empty")
    return resolved.value


async def resolve_credential_secrets(
    session: AsyncSession,
    credential: LLMProviderCredential,
) -> ResolvedLLMCredentialSecrets:
    if credential.auth_method == "api_key":
        return ResolvedLLMCredentialSecrets(
            api_key=await resolve_llm_secret(
                session,
                credential.organization_id,
                credential.api_key_secret_handle_id,
                workspace_id=credential.workspace_id,
                label="apiKey",
            )
        )
    if credential.auth_method == "oauth":
        return ResolvedLLMCredentialSecrets(
            oauth_access_token=await resolve_llm_secret(
                session,
                credential.organization_id,
                credential.oauth_access_token_secret_handle_id,
                workspace_id=credential.workspace_id,
                label="oauthAccessToken",
            ),
            oauth_refresh_token=await resolve_llm_secret(
                session,
                credential.organization_id,
                credential.oauth_refresh_token_secret_handle_id,
                workspace_id=credential.workspace_id,
                label="oauthRefreshToken",
            ),
        )
    raise InvalidLLMProviderCredentialAuthError("invalid credential auth method")


async def list_models_for_credential(
    session: AsyncSession,
    credential: LLMProviderCredential,
) -> LLMProviderModelListResponse:
    secrets = await resolve_credential_secrets(session, credential)
    if credential.provider == OPENAI_API_KEY_PROVIDER and credential.auth_method == "api_key":
        return LLMProviderModelListResponse(
            models=await fetch_openai_models(secrets.api_key)
        )
    if (
        credential.provider == OPENAI_CHATGPT_PROVIDER
        and credential.auth_method == "oauth"
        and credential.oauth_provider == "chatgpt"
    ):
        validate_chatgpt_oauth_credential(
            oauth_access_token=secrets.oauth_access_token,
            oauth_refresh_token=secrets.oauth_refresh_token,
            oauth_expires_at=credential.oauth_expires_at,
        )
        return LLMProviderModelListResponse(models=openai_chatgpt_models())
    raise InvalidLLMProviderCredentialAuthError(
        f"unsupported provider/auth combination: {credential.provider}/{credential.auth_method}"
    )


async def list_provider_credential_models(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> LLMProviderModelListResponse:
    await require_organization_member(session, user, organization_id)
    credential = await repository.get_credential(
        session,
        organization_id=organization_id,
        credential_id=credential_id,
    )
    if credential is None or not credential.is_active:
        raise LLMProviderCredentialNotFoundError("provider credential not found")
    if not user_can_see_credential(user, credential):
        raise LLMProviderCredentialNotFoundError("provider credential not found")
    return await list_models_for_credential(session, credential)


async def validate_provider_credential_by_id(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> LLMProviderCredentialValidationResponse:
    await require_organization_member(session, user, organization_id)
    credential = await repository.get_credential(
        session,
        organization_id=organization_id,
        credential_id=credential_id,
    )
    if credential is None or not credential.is_active:
        raise LLMProviderCredentialNotFoundError("provider credential not found")
    if not user_can_see_credential(user, credential):
        raise LLMProviderCredentialNotFoundError("provider credential not found")
    try:
        secrets = await resolve_credential_secrets(session, credential)
        await validate_provider_credential(
            provider=credential.provider,
            auth_method=credential.auth_method,
            secret_value=secrets.api_key,
            oauth_provider=credential.oauth_provider,
            oauth_access_token=secrets.oauth_access_token,
            oauth_refresh_token=secrets.oauth_refresh_token,
            oauth_expires_at=credential.oauth_expires_at,
        )
    except InvalidLLMProviderCredentialAuthError as exc:
        return LLMProviderCredentialValidationResponse(ok=False, message=str(exc))
    return LLMProviderCredentialValidationResponse(
        ok=True,
        message="Credential validation passed.",
    )


async def credential_supports_model(
    session: AsyncSession,
    credential: LLMProviderCredential,
    model_name: str,
) -> bool:
    normalized_model = model_name.strip()
    if not normalized_model:
        return False
    models = await list_models_for_credential(session, credential)
    return any(model.id == normalized_model for model in models.models)


def credential_response(credential: LLMProviderCredential) -> LLMProviderCredentialRead:
    return LLMProviderCredentialRead(
        id=credential.id,
        organizationId=credential.organization_id,
        workspaceId=credential.workspace_id,
        userId=credential.user_id,
        name=credential.name,
        provider=credential.provider,
        visibility=credential.visibility,
        authMethod=credential.auth_method,
        apiKeySecretHandleId=credential.api_key_secret_handle_id,
        baseUrl=credential.base_url,
        extraHeaders=credential.extra_headers or {},
        oauthProvider=credential.oauth_provider,
        oauthAccessTokenSecretHandleId=credential.oauth_access_token_secret_handle_id,
        oauthRefreshTokenSecretHandleId=credential.oauth_refresh_token_secret_handle_id,
        oauthExpiresAt=credential.oauth_expires_at,
        oauthScopes=credential.oauth_scopes or [],
        oauthMetadata=credential.oauth_metadata or {},
        isActive=credential.is_active,
        createdAt=credential.created_at,
        updatedAt=credential.updated_at,
    )


async def require_scope_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    visibility: str,
    workspace_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if visibility == "organization":
        await require_organization_admin(session, user, organization_id)
        if workspace_id is not None:
            raise InvalidLLMProviderCredentialScopeError(
                "organization-scoped credentials cannot include a workspace"
            )
        return None
    if visibility == "workspace":
        if workspace_id is None:
            raise InvalidLLMProviderCredentialScopeError(
                "workspace-scoped credentials require a workspace"
            )
        await require_workspace_admin(session, user, organization_id, workspace_id)
        return workspace_id
    if visibility == "user":
        await require_organization_member(session, user, organization_id)
        if workspace_id is not None:
            raise InvalidLLMProviderCredentialScopeError(
                "user-scoped credentials cannot include a workspace"
            )
        return None
    raise InvalidLLMProviderCredentialScopeError("invalid credential visibility")


def user_can_see_credential(user: User, credential: LLMProviderCredential) -> bool:
    return credential.visibility != "user" or credential.user_id == user.id or user.is_superuser


async def list_provider_credentials(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> LLMProviderCredentialListResponse:
    await require_organization_member(session, user, organization_id)
    credentials = await repository.list_credentials(session, organization_id=organization_id)
    return LLMProviderCredentialListResponse(
        credentials=[
            credential_response(credential)
            for credential in credentials
            if user_can_see_credential(user, credential)
        ]
    )


async def create_provider_credential(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: LLMProviderCredentialCreate,
) -> LLMProviderCredentialRead:
    name = normalize_name(payload.name)
    workspace_id = await require_scope_permission(
        session,
        user,
        organization_id,
        visibility=payload.visibility,
        workspace_id=payload.workspace_id,
    )
    if await repository.get_credential_by_name(
        session,
        organization_id=organization_id,
        name=name,
    ):
        raise DuplicateLLMProviderCredentialError("provider credential name already exists")
    credential_count = await repository.count_credentials_for_organization(
        session,
        organization_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.LLM_PROVIDER_CREDENTIALS_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=credential_count,
    )
    if workspace_id is not None:
        workspace_credential_count = await repository.count_credentials_for_workspace(
            session,
            workspace_id,
        )
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.LLM_PROVIDER_CREDENTIALS_PER_WORKSPACE,
            scope_chain=[
                ("workspace", workspace_id),
                ("organization", organization_id),
            ],
            current_count=workspace_credential_count,
        )
    if payload.visibility == "user":
        user_credential_count = await repository.count_credentials_for_user(
            session,
            organization_id=organization_id,
            user_id=user.id,
        )
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.LLM_PROVIDER_CREDENTIALS_PER_USER,
            scope_chain=[
                ("organization", organization_id),
            ],
            current_count=user_credential_count,
        )
    auth_method = payload.auth_method
    oauth_provider = normalize_oauth_provider(payload.oauth_provider)
    provider = normalize_credential_provider(
        payload.provider,
        auth_method=auth_method,
        oauth_provider=oauth_provider,
    )
    api_key_secret_handle_id = payload.api_key_secret_handle_id
    user_id = user.id if payload.visibility == "user" else None
    api_key_value = payload.api_key.get_secret_value().strip() if payload.api_key else ""
    if auth_method == "api_key" and payload.api_key is not None and not api_key_value:
        raise InvalidLLMProviderCredentialAuthError("OpenAI API key is required")
    if auth_method == "api_key" and api_key_value:
        await validate_provider_credential(
            provider=provider,
            auth_method=auth_method,
            secret_value=api_key_value,
            oauth_provider=oauth_provider,
            oauth_access_token="",
            oauth_refresh_token="",
            oauth_expires_at=payload.oauth_expires_at,
        )
        external_ref = llm_secret_path(
            organization_id=organization_id,
            workspace_id=workspace_id,
            user_id=user_id,
            provider=provider,
            name=name,
        )
        handle_workspace_id = workspace_id if payload.visibility == "workspace" else None
        await write_secret_values(
            session,
            user,
            organization_id,
            payload.api_key_secret_store_id,
            workspace_id=handle_workspace_id,
            external_ref=external_ref,
            values={"api_key": api_key_value},
            purpose="llm_credential",
        )
        api_key_handle = await create_secret_handle(
            session,
            user,
            organization_id,
            SecretHandleCreate(
                storeId=payload.api_key_secret_store_id,
                workspaceId=handle_workspace_id,
                purpose="llm_credential",
                displayName=secret_handle_display_name(name, "API key"),
                externalRef=external_ref,
                keyName="api_key",
                metadata={"provider": provider, "credentialName": name},
            ),
        )
        api_key_secret_handle_id = api_key_handle.id
    else:
        probe_credential = LLMProviderCredential(
            organization_id=organization_id,
            workspace_id=workspace_id,
            user_id=user_id,
            name=name,
            provider=provider,
            visibility=payload.visibility,
            auth_method=auth_method,
            api_key_secret_handle_id=api_key_secret_handle_id,
            oauth_provider=oauth_provider,
            oauth_access_token_secret_handle_id=payload.oauth_access_token_secret_handle_id,
            oauth_refresh_token_secret_handle_id=payload.oauth_refresh_token_secret_handle_id,
            oauth_expires_at=payload.oauth_expires_at,
            oauth_scopes=payload.oauth_scopes,
            oauth_metadata=payload.oauth_metadata,
            base_url=payload.base_url.strip(),
            extra_headers={key.strip(): value for key, value in payload.extra_headers.items()},
            is_active=True,
        )
        resolved_secrets = await resolve_credential_secrets(session, probe_credential)
        await validate_provider_credential(
            provider=provider,
            auth_method=auth_method,
            secret_value=resolved_secrets.api_key,
            oauth_provider=oauth_provider,
            oauth_access_token=resolved_secrets.oauth_access_token,
            oauth_refresh_token=resolved_secrets.oauth_refresh_token,
            oauth_expires_at=payload.oauth_expires_at,
        )

    credential = LLMProviderCredential(
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        name=name,
        provider=provider,
        visibility=payload.visibility,
        auth_method=auth_method,
        api_key_secret_handle_id=api_key_secret_handle_id,
        oauth_provider=oauth_provider,
        oauth_access_token_secret_handle_id=payload.oauth_access_token_secret_handle_id,
        oauth_refresh_token_secret_handle_id=payload.oauth_refresh_token_secret_handle_id,
        oauth_expires_at=payload.oauth_expires_at,
        oauth_scopes=payload.oauth_scopes,
        oauth_metadata=payload.oauth_metadata,
        base_url=payload.base_url.strip(),
        extra_headers={key.strip(): value for key, value in payload.extra_headers.items()},
        is_active=True,
    )
    session.add(credential)
    await session.flush()
    await session.refresh(credential)
    return credential_response(credential)


async def update_provider_credential(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    credential_id: uuid.UUID,
    payload: LLMProviderCredentialUpdate,
) -> LLMProviderCredentialRead:
    credential = await repository.get_credential(
        session,
        organization_id=organization_id,
        credential_id=credential_id,
    )
    if credential is None:
        raise LLMProviderCredentialNotFoundError("provider credential not found")

    visibility = payload.visibility or credential.visibility
    workspace_id = (
        payload.workspace_id
        if "workspace_id" in payload.model_fields_set
        else credential.workspace_id
    )
    await require_scope_permission(
        session,
        user,
        organization_id,
        visibility=visibility,
        workspace_id=workspace_id,
    )

    if payload.name is not None:
        name = normalize_name(payload.name)
        existing = await repository.get_credential_by_name(
            session,
            organization_id=organization_id,
            name=name,
        )
        if existing is not None and existing.id != credential.id:
            raise DuplicateLLMProviderCredentialError("provider credential name already exists")
        credential.name = name
    if payload.provider is not None:
        credential.provider = normalize_provider(payload.provider)
    next_auth_method = payload.auth_method or credential.auth_method
    if payload.visibility is not None or "workspace_id" in payload.model_fields_set:
        credential.visibility = visibility
        credential.workspace_id = workspace_id
        credential.user_id = user.id if visibility == "user" else None
    if payload.auth_method is not None:
        credential.auth_method = payload.auth_method
    if "api_key_secret_handle_id" in payload.model_fields_set:
        credential.api_key_secret_handle_id = payload.api_key_secret_handle_id
    if payload.oauth_provider is not None:
        credential.oauth_provider = normalize_oauth_provider(payload.oauth_provider)
    if "oauth_access_token_secret_handle_id" in payload.model_fields_set:
        credential.oauth_access_token_secret_handle_id = (
            payload.oauth_access_token_secret_handle_id
        )
    if "oauth_refresh_token_secret_handle_id" in payload.model_fields_set:
        credential.oauth_refresh_token_secret_handle_id = (
            payload.oauth_refresh_token_secret_handle_id
        )
    if "oauth_expires_at" in payload.model_fields_set:
        credential.oauth_expires_at = payload.oauth_expires_at
    if payload.oauth_scopes is not None:
        credential.oauth_scopes = payload.oauth_scopes
    if payload.oauth_metadata is not None:
        credential.oauth_metadata = payload.oauth_metadata
    if next_auth_method == "api_key":
        credential.auth_method = "api_key"
        credential.oauth_provider = ""
        credential.oauth_access_token_secret_handle_id = None
        credential.oauth_refresh_token_secret_handle_id = None
        credential.oauth_expires_at = None
        credential.oauth_scopes = []
        credential.oauth_metadata = {}
    else:
        credential.auth_method = "oauth"
        if payload.api_key_secret_handle_id is not None:
            raise InvalidLLMProviderCredentialAuthError(
                "apiKeySecretHandleId is only valid for api_key credentials"
            )
        credential.api_key_secret_handle_id = None
    if payload.base_url is not None:
        credential.base_url = payload.base_url.strip()
    if payload.extra_headers is not None:
        credential.extra_headers = {
            key.strip(): value for key, value in payload.extra_headers.items()
        }
    if payload.is_active is not None:
        credential.is_active = payload.is_active

    credential.provider = normalize_credential_provider(
        credential.provider,
        auth_method=credential.auth_method,
        oauth_provider=credential.oauth_provider,
    )

    resolved_secrets = await resolve_credential_secrets(session, credential)
    await validate_provider_credential(
        provider=credential.provider,
        auth_method=credential.auth_method,
        secret_value=resolved_secrets.api_key,
        oauth_provider=credential.oauth_provider,
        oauth_access_token=resolved_secrets.oauth_access_token,
        oauth_refresh_token=resolved_secrets.oauth_refresh_token,
        oauth_expires_at=credential.oauth_expires_at,
    )

    await session.flush()
    await session.refresh(credential)
    return credential_response(credential)


async def delete_provider_credential(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> None:
    credential = await repository.get_credential(
        session,
        organization_id=organization_id,
        credential_id=credential_id,
    )
    if credential is None:
        raise LLMProviderCredentialNotFoundError("provider credential not found")
    await require_scope_permission(
        session,
        user,
        organization_id,
        visibility=credential.visibility,
        workspace_id=credential.workspace_id,
    )
    await session.delete(credential)
