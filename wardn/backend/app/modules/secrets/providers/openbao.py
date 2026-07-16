import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.outbound_http import UnsafeOutboundURLError, validate_outbound_url
from app.modules.secrets.exceptions import InvalidSecretHandleError, InvalidSecretStoreError
from app.modules.secrets.models import SecretHandle, SecretStore
from app.modules.secrets.provider import (
    ResolvedSecret,
    SecretResolutionContext,
    SecretValidationResult,
    SecretWriteResult,
)
from app.modules.secrets.providers.openbao_profiles import (
    OpenBaoAuthProfile,
    parse_openbao_auth_profiles,
    read_profile_file,
)

STANDARD_KV_MOUNT = "secret"
DEFAULT_TIMEOUT_SECONDS = 15.0
OPERATOR_MANAGED_STORE_KEYS = {
    "authMount",
    "auth_mount",
    "namespace",
    "tlsVerify",
    "tls_verify",
}


@dataclass
class OpenBaoToken:
    token: str
    renewable: bool = False
    lease_duration: int = 0


class OpenBaoSecretProvider:
    name = "openbao"

    def __init__(
        self,
        *,
        auth_profiles: Mapping[str, OpenBaoAuthProfile] | None = None,
        auth_file_root: str | None = None,
        url_validator: Callable[[str], Any] | None = None,
    ) -> None:
        self._token_cache: dict[str, OpenBaoToken] = {}
        self._configured_auth_profiles = auth_profiles
        self._configured_auth_file_root = auth_file_root
        self._url_validator = url_validator or validate_outbound_url

    async def validate_store(self, store: SecretStore) -> SecretValidationResult:
        try:
            self._store_settings(store)
            self._auth_settings(store)
        except InvalidSecretStoreError as exc:
            return SecretValidationResult(ok=False, message=str(exc))
        return SecretValidationResult(ok=True, message="OpenBao store configuration is valid.")

    async def validate_connection(self, store: SecretStore) -> SecretValidationResult:
        try:
            auth = self._auth_settings(store)
            self._token_cache.pop(self._cache_key(store, auth), None)
            settings = self._store_settings(store)
            token = await self._client_token(store)
            await self._validate_kv_probe(store, settings, token)
        except Exception as exc:
            return SecretValidationResult(ok=False, message=str(exc))
        return SecretValidationResult(
            ok=True,
            message=(
                "OpenBao validation succeeded: authenticated, wrote, read, "
                "and deleted a KV v2 probe secret."
            ),
        )

    async def validate_handle(
        self,
        store: SecretStore,
        handle: SecretHandle,
    ) -> SecretValidationResult:
        if not handle.external_ref.strip().strip("/"):
            return SecretValidationResult(ok=False, message="externalRef is required")
        if not handle.key_name.strip():
            return SecretValidationResult(
                ok=False,
                message="keyName is required for OpenBao KV v2 secrets",
            )
        try:
            await self.resolve(
                store,
                handle,
                SecretResolutionContext(
                    organization_id=str(handle.organization_id),
                    workspace_id=str(handle.workspace_id) if handle.workspace_id else None,
                    purpose=handle.purpose,
                ),
            )
        except Exception as exc:
            return SecretValidationResult(ok=False, message=str(exc))
        return SecretValidationResult(ok=True, message="OpenBao secret handle resolved.")

    async def resolve(
        self,
        store: SecretStore,
        handle: SecretHandle,
        context: SecretResolutionContext,
    ) -> ResolvedSecret:
        settings = self._store_settings(store)
        token = await self._client_token(store)
        mount = str(settings["kv_mount"]).strip("/")
        secret_path = handle.external_ref.strip().strip("/")
        url = f"{settings['base_url']}/v1/{mount}/data/{secret_path}"
        params = {}
        if handle.version:
            params["version"] = handle.version
        headers = self._headers(settings, token.token)

        async with httpx.AsyncClient(
            timeout=float(settings["timeout_seconds"]),
            verify=settings["tls_verify"],
            follow_redirects=False,
        ) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code in {401, 403}:
                token = await self._refresh_client_token(store)
                headers = self._headers(settings, token.token)
                response = await client.get(url, headers=headers, params=params)
        if response.status_code == 404:
            raise InvalidSecretHandleError("OpenBao secret was not found")
        if not response.is_success:
            raise InvalidSecretHandleError(
                f"OpenBao secret read failed with HTTP {response.status_code}"
            )
        payload = response_json(response)
        data = record(record(payload.get("data")).get("data"))
        key_name = handle.key_name.strip()
        if key_name not in data:
            raise InvalidSecretHandleError("OpenBao secret key was not found")
        value = data[key_name]
        if not isinstance(value, str):
            value = json.dumps(value, separators=(",", ":"), sort_keys=True)
        metadata = record(record(payload.get("data")).get("metadata"))
        version = metadata.get("version")
        return ResolvedSecret(
            value=value,
            version=str(version) if version is not None else handle.version or None,
        )

    async def write(
        self,
        store: SecretStore,
        external_ref: str,
        values: dict[str, str],
        context: SecretResolutionContext,
    ) -> SecretWriteResult:
        settings = self._store_settings(store)
        token = await self._client_token(store)
        mount = str(settings["kv_mount"]).strip("/")
        secret_path = external_ref.strip().strip("/")
        if not secret_path:
            raise InvalidSecretHandleError("OpenBao secret path is required")
        if not values:
            raise InvalidSecretHandleError("OpenBao secret values are required")
        url = f"{settings['base_url']}/v1/{mount}/data/{secret_path}"
        headers = self._headers(settings, token.token)

        async with httpx.AsyncClient(
            timeout=float(settings["timeout_seconds"]),
            verify=settings["tls_verify"],
            follow_redirects=False,
        ) as client:
            response = await client.post(url, headers=headers, json={"data": values})
            if response.status_code in {401, 403}:
                token = await self._refresh_client_token(store)
                headers = self._headers(settings, token.token)
                response = await client.post(url, headers=headers, json={"data": values})
        if not response.is_success:
            raise InvalidSecretHandleError(
                f"OpenBao secret write failed with HTTP {response.status_code}"
            )
        data = record(response_json(response).get("data"))
        version = data.get("version")
        return SecretWriteResult(version=str(version) if version is not None else None)

    def _store_settings(self, store: SecretStore) -> dict[str, Any]:
        config = store.config or {}
        operator_managed_keys = OPERATOR_MANAGED_STORE_KEYS.intersection(config)
        if operator_managed_keys:
            raise InvalidSecretStoreError(
                "OpenBao authentication, namespace, and TLS settings are operator-managed"
            )
        auth = self._auth_settings(store)
        base_url = string_value(config.get("baseUrl") or config.get("base_url")).rstrip("/")
        if not base_url:
            raise InvalidSecretStoreError("OpenBao baseUrl is required")
        if base_url != auth["base_url"]:
            raise InvalidSecretStoreError(
                "OpenBao baseUrl must match the operator-defined authentication profile"
            )
        try:
            self._url_validator(base_url)
        except UnsafeOutboundURLError as exc:
            raise InvalidSecretStoreError(f"OpenBao baseUrl was rejected: {exc}") from exc
        kv_mount = string_value(
            config.get("kvMount") or config.get("kv_mount") or STANDARD_KV_MOUNT
        )
        return {
            "base_url": base_url,
            "namespace": auth["namespace"],
            "kv_mount": kv_mount,
            "auth_mount": auth["auth_mount"],
            "tls_verify": auth["tls_verify"],
            "timeout_seconds": config.get("timeoutSeconds")
            or config.get("timeout_seconds")
            or DEFAULT_TIMEOUT_SECONDS,
        }

    def _auth_profiles(self) -> Mapping[str, OpenBaoAuthProfile]:
        if self._configured_auth_profiles is not None:
            return self._configured_auth_profiles
        return parse_openbao_auth_profiles(get_settings().openbao_auth_profiles_json)

    def _auth_file_root(self) -> str:
        if self._configured_auth_file_root is not None:
            return self._configured_auth_file_root
        return get_settings().openbao_auth_file_root

    def _auth_settings(self, store: SecretStore) -> dict[str, Any]:
        auth_config = store.auth_config or {}
        if set(auth_config) != {"profile"}:
            raise InvalidSecretStoreError(
                "OpenBao authConfig must contain only an operator-defined profile name"
            )
        profile_name = string_value(auth_config.get("profile"))
        profile = self._auth_profiles().get(profile_name)
        if profile is None:
            raise InvalidSecretStoreError("OpenBao authentication profile is not configured")
        settings = profile.model_dump()
        settings["profile"] = profile_name
        return settings

    async def _client_token(self, store: SecretStore) -> OpenBaoToken:
        settings = self._store_settings(store)
        auth = self._auth_settings(store)
        cache_key = self._cache_key(store, auth)
        cached = self._token_cache.get(cache_key)
        if cached is not None:
            return cached

        if auth["method"] == "kubernetes":
            token = await self._login_kubernetes(settings, auth)
        else:
            token = await self._login_approle(settings, auth)
        self._token_cache[cache_key] = token
        return token

    async def _refresh_client_token(self, store: SecretStore) -> OpenBaoToken:
        auth = self._auth_settings(store)
        self._token_cache.pop(self._cache_key(store, auth), None)
        return await self._client_token(store)

    def _cache_key(self, store: SecretStore, auth: dict[str, Any]) -> str:
        updated_at = store.updated_at.isoformat() if store.updated_at else ""
        return f"{store.id}:{auth['profile']}:{updated_at}"

    async def _validate_kv_probe(
        self,
        store: SecretStore,
        settings: dict[str, Any],
        token: OpenBaoToken,
    ) -> None:
        mount = str(settings["kv_mount"]).strip("/")
        probe_id = uuid.uuid4().hex
        secret_path_parts = ["wardn", "orgs", str(store.organization_id)]
        if store.workspace_id:
            secret_path_parts.extend(["workspaces", str(store.workspace_id)])
        secret_path_parts.extend(["validation", probe_id])
        secret_path = "/".join(secret_path_parts)
        marker = f"wardn-validation-{probe_id}"
        headers = self._headers(settings, token.token)
        base_url = settings["base_url"]
        timeout = float(settings["timeout_seconds"])
        tls_verify = settings["tls_verify"]

        async with httpx.AsyncClient(
            timeout=timeout,
            verify=tls_verify,
            follow_redirects=False,
        ) as client:
            write_response = await client.post(
                f"{base_url}/v1/{mount}/data/{secret_path}",
                headers=headers,
                json={"data": {"wardn_validation": marker}},
            )
            if not write_response.is_success:
                raise InvalidSecretStoreError(
                    f"OpenBao validation write failed with HTTP {write_response.status_code}"
                )

            read_response = await client.get(
                f"{base_url}/v1/{mount}/data/{secret_path}",
                headers=headers,
                params={},
            )
            if not read_response.is_success:
                raise InvalidSecretStoreError(
                    f"OpenBao validation read failed with HTTP {read_response.status_code}"
                )
            data = record(record(response_json(read_response).get("data")).get("data"))
            if data.get("wardn_validation") != marker:
                raise InvalidSecretStoreError("OpenBao validation read returned unexpected data")

            delete_response = await client.delete(
                f"{base_url}/v1/{mount}/metadata/{secret_path}",
                headers=headers,
            )
            if not delete_response.is_success:
                raise InvalidSecretStoreError(
                    f"OpenBao validation cleanup failed with HTTP {delete_response.status_code}"
                )

    async def _login_kubernetes(
        self,
        settings: dict[str, Any],
        auth: dict[str, Any],
    ) -> OpenBaoToken:
        jwt = read_profile_file(
            self._auth_file_root(),
            auth["token_file"],
            "Kubernetes service account token",
        )
        url = f"{settings['base_url']}/v1/auth/{settings['auth_mount'].strip('/')}/login"
        payload = {"role": auth["role"], "jwt": jwt}
        return await self._login(settings, url, payload)

    async def _login_approle(
        self,
        settings: dict[str, Any],
        auth: dict[str, Any],
    ) -> OpenBaoToken:
        role_id = read_profile_file(
            self._auth_file_root(), auth["role_id_file"], "AppRole role_id"
        )
        secret_id = read_profile_file(
            self._auth_file_root(), auth["secret_id_file"], "AppRole secret_id"
        )
        url = f"{settings['base_url']}/v1/auth/{settings['auth_mount'].strip('/')}/login"
        payload = {"role_id": role_id, "secret_id": secret_id}
        return await self._login(settings, url, payload)

    async def _login(
        self,
        settings: dict[str, Any],
        url: str,
        payload: dict[str, str],
    ) -> OpenBaoToken:
        async with httpx.AsyncClient(
            timeout=float(settings["timeout_seconds"]),
            verify=settings["tls_verify"],
            follow_redirects=False,
        ) as client:
            response = await client.post(url, headers=self._headers(settings), json=payload)
        if not response.is_success:
            message = f"OpenBao login failed with HTTP {response.status_code}"
            detail = response_error_detail(response)
            if detail:
                message = f"{message}: {detail}"
            raise InvalidSecretStoreError(message)
        auth = record(response_json(response).get("auth"))
        token = string_value(auth.get("client_token"))
        if not token:
            raise InvalidSecretStoreError("OpenBao login response did not include a client token")
        return OpenBaoToken(
            token=token,
            renewable=bool(auth.get("renewable")),
            lease_duration=int(auth.get("lease_duration") or 0),
        )

    def _headers(self, settings: dict[str, Any], token: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        namespace = settings.get("namespace")
        if namespace:
            headers["X-Vault-Namespace"] = str(namespace)
        if token:
            headers["X-Vault-Token"] = token
        return headers


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise InvalidSecretStoreError("OpenBao response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidSecretStoreError("OpenBao response was not a JSON object")
    return payload


def response_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("errors")
    if isinstance(errors, list):
        return "; ".join(str(error).strip() for error in errors if str(error).strip())
    if isinstance(errors, str):
        return errors.strip()
    return ""
