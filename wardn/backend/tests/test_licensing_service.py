import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from joserfc import jws
from joserfc.jwk import OKPKey
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.licensing import service
from app.modules.licensing.exceptions import InvalidLicenseLeaseError


def test_automatic_renewal_defaults_to_hourly() -> None:
    assert Settings().licensing_renewal_interval_seconds == 3_600


def install_test_public_key(monkeypatch, key: OKPKey) -> None:
    monkeypatch.setattr(
        service,
        "OFFICIAL_PUBLIC_KEY_JWKS",
        {key.kid: key.as_dict(private=False)},
    )


def signed_lease(
    key: OKPKey,
    instance_id: uuid.UUID,
    *,
    now: datetime,
    sequence: int = 1,
) -> str:
    payload = {
        "issuer": service.OFFICIAL_LICENSE_ISSUER,
        "audience": "wardn-ai",
        "license_id": "lic_test",
        "instance_id": str(instance_id),
        "edition": "business",
        "features": {"advancedGuardrails": True},
        "limits": {"agents.per_organization": 100},
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "grace_until": (now + timedelta(days=7)).isoformat(),
        "lease_sequence": sequence,
    }
    return jws.serialize_compact(
        {"alg": "Ed25519", "kid": key.kid},
        json.dumps(payload),
        key,
        algorithms=["Ed25519"],
    )


def test_signed_lease_verifies_and_provides_entitlements(monkeypatch) -> None:
    key = OKPKey.generate_key(auto_kid=True)
    install_test_public_key(monkeypatch, key)
    instance_id = uuid.uuid4()
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    claims = service.verify_signed_lease(
        signed_lease(key, instance_id, now=now),
        instance_id=instance_id,
        settings=Settings(),
    )

    entitlements = service.entitlements_from_claims(claims, now=now)

    assert entitlements.state == "licensed"
    assert entitlements.edition == "business"
    assert entitlements.limits["agents.per_organization"] == 100
    assert entitlements.features["advancedGuardrails"] is True


def test_signed_lease_cannot_be_used_by_another_instance(monkeypatch) -> None:
    key = OKPKey.generate_key(auto_kid=True)
    install_test_public_key(monkeypatch, key)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)

    with pytest.raises(InvalidLicenseLeaseError, match="another Wardn instance"):
        service.verify_signed_lease(
            signed_lease(key, uuid.uuid4(), now=now),
            instance_id=uuid.uuid4(),
            settings=Settings(),
        )


def test_expired_grace_falls_back_to_community_entitlements(monkeypatch) -> None:
    key = OKPKey.generate_key(auto_kid=True)
    install_test_public_key(monkeypatch, key)
    instance_id = uuid.uuid4()
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    claims = service.verify_signed_lease(
        signed_lease(key, instance_id, now=now),
        instance_id=instance_id,
        settings=Settings(),
    )

    entitlements = service.entitlements_from_claims(claims, now=now + timedelta(days=8))

    assert entitlements.state == "community"
    assert entitlements.limits["agents.per_organization"] == 10


@pytest.mark.asyncio
async def test_online_renewal_uses_opaque_activation_key(monkeypatch) -> None:
    key = OKPKey.generate_key(auto_kid=True)
    install_test_public_key(monkeypatch, key)
    instance_id = uuid.uuid4()
    now = datetime.now(UTC)
    lease = signed_lease(key, instance_id, now=now)
    settings = Settings().model_copy(
        update={
            "licensing_activation_key": SecretStr("wardn_lic_secret"),
        }
    )

    class Installation:
        signed_lease = ""
        renewal_token = ""
        lease_imported_at = None

        def __init__(self) -> None:
            self.instance_id = instance_id

    installation = Installation()

    async def get_or_create_installation(session):
        return installation

    async def store_signed_lease(
        session, target, *, signed_lease, renewal_token, imported_at
    ):
        target.signed_lease = signed_lease
        target.renewal_token = renewal_token

    monkeypatch.setattr(
        service.repository,
        "get_or_create_installation",
        get_or_create_installation,
    )
    monkeypatch.setattr(service.repository, "store_signed_lease", store_signed_lease)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{service.OFFICIAL_LICENSE_SERVER_URL}/v1/leases/renew"
        assert request.headers["Authorization"] == "Bearer wardn_lic_secret"
        assert json.loads(request.content)["instanceId"] == str(instance_id)
        return httpx.Response(
            200,
            json={"signedLease": lease, "renewalToken": "wardn_renew_test_secret_1234567890"},
        )

    user = type("User", (), {"is_superuser": True})()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        status = await service.renew_license(object(), user, settings=settings, client=client)

    assert status.state == "licensed"
    assert installation.signed_lease == lease
    assert installation.renewal_token == "wardn_renew_test_secret_1234567890"
