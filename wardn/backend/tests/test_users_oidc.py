import time

import pytest
from joserfc import jwk, jwt

from app.core.config import Settings
from app.modules.users import oidc
from app.modules.users.exceptions import OIDCAuthenticationError


def oidc_settings(**overrides) -> Settings:
    values = {
        "auth_mode": "oidc",
        "session_secret": "test-session-secret",
        "frontend_base_url": "https://app.example.com",
        "oidc_issuer_url": "https://issuer.example.com",
        "oidc_client_id": "wardn-client",
        "oidc_client_secret": "wardn-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_oidc_state_round_trip() -> None:
    settings = oidc_settings()

    state, cookie = oidc.create_oidc_state(settings, redirect_to="/org/acme")

    verified = oidc.verify_oidc_state(settings, cookie, state.state)
    assert verified.state == state.state
    assert verified.nonce == state.nonce
    assert verified.redirect_to == "/org/acme"


def test_oidc_state_rejects_mismatched_state() -> None:
    settings = oidc_settings()
    _state, cookie = oidc.create_oidc_state(settings)

    with pytest.raises(OIDCAuthenticationError):
        oidc.verify_oidc_state(settings, cookie, "wrong-state")


def test_oidc_redirect_uri_defaults_to_frontend_proxy_callback() -> None:
    assert (
        oidc.oidc_redirect_uri(oidc_settings(frontend_base_url="https://wardn.example.com"))
        == "https://wardn.example.com/api/auth/oidc/callback"
    )


@pytest.mark.asyncio
async def test_verify_oidc_identity_validates_signed_id_token(monkeypatch) -> None:
    signing_key = jwk.generate_key("RSA", 2048, parameters={"kid": "test-key"})
    settings = oidc_settings()
    metadata = {
        "issuer": "https://issuer.example.com",
        "jwks_uri": "https://issuer.example.com/jwks",
    }
    id_token = jwt.encode(
        {"alg": "RS256", "kid": "test-key"},
        {
            "iss": "https://issuer.example.com",
            "sub": "subject-1",
            "aud": "wardn-client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "nonce": "nonce-1",
            "email": "Admin@Example.COM",
            "email_verified": True,
            "given_name": "Ada",
            "family_name": "Lovelace",
        },
        signing_key,
    )

    async def fetch_jwks(_metadata):
        return {"keys": [signing_key.as_dict(private=False)]}

    monkeypatch.setattr(oidc, "fetch_jwks", fetch_jwks)

    identity = await oidc.verify_oidc_identity(
        settings,
        metadata,
        {"id_token": id_token},
        nonce="nonce-1",
    )

    assert identity.email == "admin@example.com"
    assert identity.first_name == "Ada"
    assert identity.last_name == "Lovelace"
    assert identity.subject == "subject-1"


@pytest.mark.asyncio
async def test_verify_oidc_identity_rejects_wrong_nonce(monkeypatch) -> None:
    signing_key = jwk.generate_key("RSA", 2048, parameters={"kid": "test-key"})
    settings = oidc_settings()
    metadata = {"jwks_uri": "https://issuer.example.com/jwks"}
    id_token = jwt.encode(
        {"alg": "RS256", "kid": "test-key"},
        {
            "iss": "https://issuer.example.com",
            "sub": "subject-1",
            "aud": "wardn-client",
            "exp": int(time.time()) + 300,
            "nonce": "expected-nonce",
            "email": "admin@example.com",
            "email_verified": True,
        },
        signing_key,
    )

    async def fetch_jwks(_metadata):
        return {"keys": [signing_key.as_dict(private=False)]}

    monkeypatch.setattr(oidc, "fetch_jwks", fetch_jwks)

    with pytest.raises(OIDCAuthenticationError):
        await oidc.verify_oidc_identity(
            settings,
            metadata,
            {"id_token": id_token},
            nonce="wrong-nonce",
        )
