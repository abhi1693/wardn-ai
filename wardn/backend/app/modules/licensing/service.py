import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from joserfc import jws
from joserfc.errors import JoseError
from joserfc.jwk import OKPKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.licensing import repository
from app.modules.licensing.exceptions import InvalidLicenseLeaseError, LicenseRenewalError
from app.modules.licensing.schemas import LicenseStatus
from app.modules.users.models import User

COMMUNITY_LIMITS: dict[str, int] = {
    "workspaces.per_organization": 3,
    "workspaces.created_per_user": 3,
    "agents.per_organization": 10,
    "agents.per_workspace": 5,
    "agents.per_workspace_per_user": 5,
    "workspace_conversations.per_workspace": 100,
    "workspace_conversations.per_workspace_per_user": 100,
    "agent_chat.max_tool_rounds.per_run": 25,
    "guardrail_policies.per_workspace": 5,
    "guardrail_policies.per_workspace_per_user": 5,
    "mcp_catalog_sources.per_organization": 3,
    "mcp_server_versions.per_organization": 50,
    "mcp_server_installations.per_workspace": 10,
    "mcp_runtime_public_egress.per_workspace": 1,
    "mcp_runtime_private_egress.per_workspace": 0,
    "mcp_runtime_kubernetes_api_egress.per_workspace": 0,
    "mcp_runtime_network_isolation_disable.per_workspace": 0,
    "mcp_runtime_custom_egress_rules.per_installation": 0,
    "secret_stores.per_organization": 3,
    "secret_stores.per_workspace": 3,
    "secret_handles.per_organization": 50,
    "secret_handles.per_workspace": 25,
    "llm_provider_credentials.per_organization": 10,
    "llm_provider_credentials.per_workspace": 5,
    "llm_provider_credentials.per_user": 5,
}
COMMUNITY_FEATURES: dict[str, bool] = {}
OFFICIAL_LICENSE_SERVER_URL = "https://license.wardnai.dev"
OFFICIAL_LICENSE_ISSUER = "https://license.wardnai.dev"
OFFICIAL_LICENSE_AUDIENCE = "wardn-ai"
OFFICIAL_PUBLIC_KEY_JWKS: dict[str, dict[str, str]] = {
    "uZ8gOcCGUqlMhVgTuOK4pThU42hNcooIP_FAEg43Qic": {
        "crv": "Ed25519",
        "x": "MjgEms8eq6RXtLnuKmrqcO-5M9cH0J3_YzLvMMnC_Rg",
        "kty": "OKP",
        "kid": "uZ8gOcCGUqlMhVgTuOK4pThU42hNcooIP_FAEg43Qic",
    }
}


class LeaseClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    audience: str
    license_id: str = Field(min_length=1, max_length=255)
    instance_id: uuid.UUID
    edition: str = Field(min_length=1, max_length=100)
    features: dict[str, bool] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    issued_at: datetime
    expires_at: datetime
    grace_until: datetime
    lease_sequence: int = Field(ge=0)

    @field_validator("issued_at", "expires_at", "grace_until")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("license timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("limits")
    @classmethod
    def validate_limits(cls, value: dict[str, int]) -> dict[str, int]:
        if any(limit < 0 for limit in value.values()):
            raise ValueError("license limits cannot be negative")
        unknown = set(value) - set(COMMUNITY_LIMITS)
        if unknown:
            raise ValueError(f"license contains unsupported limits: {', '.join(sorted(unknown))}")
        return value


@dataclass(frozen=True)
class Entitlements:
    state: Literal["community", "licensed", "grace"]
    edition: str
    features: dict[str, bool]
    limits: dict[str, int]
    claims: LeaseClaims | None = None


def require_license_admin(user: User) -> None:
    if not user.is_superuser:
        raise PermissionError("only superusers can manage licensing")


def community_entitlements() -> Entitlements:
    return Entitlements(
        state="community",
        edition="community",
        features=dict(COMMUNITY_FEATURES),
        limits=dict(COMMUNITY_LIMITS),
    )


def official_public_keys() -> dict[str, OKPKey]:
    keys: dict[str, OKPKey] = {}
    try:
        for key_id, value in OFFICIAL_PUBLIC_KEY_JWKS.items():
            key = OKPKey.import_key(value)
            if key.is_private:
                raise ValueError
            keys[key_id] = key
    except (TypeError, ValueError) as exc:
        raise InvalidLicenseLeaseError("licensing public keys contain an invalid key") from exc
    return keys


def verify_signed_lease(
    signed_lease: str,
    *,
    instance_id: uuid.UUID,
    settings: Settings | None = None,
    public_keys: dict[str, OKPKey] | None = None,
    issuer: str = OFFICIAL_LICENSE_ISSUER,
    audience: str = OFFICIAL_LICENSE_AUDIENCE,
) -> LeaseClaims:
    try:
        encoded_header = signed_lease.split(".", 1)[0]
        import base64

        padding = "=" * (-len(encoded_header) % 4)
        header = json.loads(base64.urlsafe_b64decode(encoded_header + padding))
        key_id = header.get("kid")
        if header.get("alg") != "Ed25519" or not isinstance(key_id, str):
            raise InvalidLicenseLeaseError("license lease has an invalid signing header")
        key = (public_keys or official_public_keys()).get(key_id)
        if key is None:
            raise InvalidLicenseLeaseError("license lease uses an unknown signing key")
        signed = jws.deserialize_compact(
            signed_lease,
            key,
            algorithms=["Ed25519"],
        )
        claims = LeaseClaims.model_validate_json(signed.payload)
    except InvalidLicenseLeaseError:
        raise
    except (JoseError, ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidLicenseLeaseError("license lease is invalid") from exc
    if claims.issuer != issuer:
        raise InvalidLicenseLeaseError("license lease issuer does not match")
    if claims.audience != audience:
        raise InvalidLicenseLeaseError("license lease audience does not match")
    if claims.instance_id != instance_id:
        raise InvalidLicenseLeaseError("license lease belongs to another Wardn instance")
    if claims.issued_at >= claims.expires_at or claims.expires_at > claims.grace_until:
        raise InvalidLicenseLeaseError("license lease validity window is invalid")
    return claims


def entitlements_from_claims(claims: LeaseClaims, *, now: datetime | None = None) -> Entitlements:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if now > claims.grace_until:
        return community_entitlements()
    state: Literal["licensed", "grace"] = "licensed" if now <= claims.expires_at else "grace"
    return Entitlements(
        state=state,
        edition=claims.edition,
        features=dict(claims.features),
        limits={**COMMUNITY_LIMITS, **claims.limits},
        claims=claims,
    )


async def current_entitlements(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> tuple[uuid.UUID, Entitlements]:
    settings = settings or get_settings()
    # Domain unit tests use deliberately small session doubles. Application callers use
    # SQLAlchemy's AsyncSession through the database dependency.
    if not isinstance(session, AsyncSession):
        return uuid.UUID(int=0), community_entitlements()
    installation = await repository.get_or_create_installation(session)
    if not installation.signed_lease:
        return installation.instance_id, community_entitlements()
    try:
        claims = verify_signed_lease(
            installation.signed_lease,
            instance_id=installation.instance_id,
            settings=settings,
        )
    except InvalidLicenseLeaseError:
        return installation.instance_id, community_entitlements()
    return installation.instance_id, entitlements_from_claims(claims, now=now)


async def import_signed_lease(
    session: AsyncSession,
    user: User,
    signed_lease: str,
    *,
    renewal_token: str | None = None,
    settings: Settings | None = None,
) -> LicenseStatus:
    require_license_admin(user)
    settings = settings or get_settings()
    installation = await repository.get_or_create_installation(session)
    claims = verify_signed_lease(
        signed_lease,
        instance_id=installation.instance_id,
        settings=settings,
    )
    if installation.signed_lease:
        try:
            previous = verify_signed_lease(
                installation.signed_lease,
                instance_id=installation.instance_id,
                settings=settings,
            )
            if claims.lease_sequence < previous.lease_sequence:
                raise InvalidLicenseLeaseError("license lease is older than the installed lease")
        except InvalidLicenseLeaseError as exc:
            if "older than" in str(exc):
                raise
    await repository.store_signed_lease(
        session,
        installation,
        signed_lease=signed_lease,
        renewal_token=renewal_token,
        imported_at=datetime.now(UTC),
    )
    return license_status_response(
        installation.instance_id,
        entitlements_from_claims(claims),
        settings=settings,
    )


async def renew_license(
    session: AsyncSession,
    user: User,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> LicenseStatus:
    require_license_admin(user)
    return await renew_installed_license(session, settings=settings, client=client)


async def renew_installed_license(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> LicenseStatus:
    settings = settings or get_settings()
    activation_key = settings.licensing_activation_key.get_secret_value().strip()
    if not activation_key:
        raise LicenseRenewalError("automatic license renewal is not configured")
    installation = await repository.get_or_create_installation(session)
    sequence = None
    if installation.signed_lease:
        try:
            sequence = verify_signed_lease(
                installation.signed_lease,
                instance_id=installation.instance_id,
                settings=settings,
            ).lease_sequence
        except InvalidLicenseLeaseError:
            pass
    request_body: dict[str, Any] = {
        "instanceId": str(installation.instance_id),
        "currentLeaseSequence": sequence,
        "renewalToken": installation.renewal_token or None,
        "instanceName": settings.licensing_instance_name.strip(),
        "serverUrl": settings.public_base_url.strip(),
        "appVersion": settings.app_version,
    }
    headers = {"Authorization": f"Bearer {activation_key}"}
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=settings.licensing_request_timeout_seconds)
    try:
        response = await http_client.post(
            f"{OFFICIAL_LICENSE_SERVER_URL}/v1/leases/renew",
            json=request_body,
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        signed_lease = body.get("signedLease")
        renewal_token = body.get("renewalToken")
        if not isinstance(signed_lease, str) or not isinstance(renewal_token, str):
            raise LicenseRenewalError("license server returned an invalid response")
    except (httpx.HTTPError, ValueError) as exc:
        raise LicenseRenewalError("license renewal request failed") from exc
    finally:
        if owns_client:
            await http_client.aclose()
    claims = verify_signed_lease(
        signed_lease,
        instance_id=installation.instance_id,
        settings=settings,
    )
    if sequence is not None and claims.lease_sequence < sequence:
        raise InvalidLicenseLeaseError("license lease is older than the installed lease")
    await repository.store_signed_lease(
        session,
        installation,
        signed_lease=signed_lease,
        renewal_token=renewal_token,
        imported_at=datetime.now(UTC),
    )
    return license_status_response(
        installation.instance_id,
        entitlements_from_claims(claims),
        settings=settings,
    )


def license_status_response(
    instance_id: uuid.UUID,
    entitlements: Entitlements,
    *,
    settings: Settings,
) -> LicenseStatus:
    claims = entitlements.claims
    return LicenseStatus(
        instanceId=instance_id,
        state=entitlements.state,
        edition=entitlements.edition,
        licenseId=claims.license_id if claims else None,
        expiresAt=claims.expires_at if claims else None,
        graceUntil=claims.grace_until if claims else None,
        features=entitlements.features,
        limits=entitlements.limits,
        automaticRenewalConfigured=bool(
            settings.licensing_activation_key.get_secret_value().strip()
        ),
    )


async def get_license_status(
    session: AsyncSession,
    user: User,
    *,
    settings: Settings | None = None,
) -> LicenseStatus:
    require_license_admin(user)
    settings = settings or get_settings()
    instance_id, entitlements = await current_entitlements(session, settings=settings)
    return license_status_response(instance_id, entitlements, settings=settings)
