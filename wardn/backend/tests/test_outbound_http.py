from urllib.request import Request

import pytest

from app.core import outbound_http
from app.core.outbound_http import (
    NoRedirectHandler,
    OutboundURLPolicy,
    UnsafeOutboundURLError,
    validate_outbound_url,
)

PUBLIC_POLICY = OutboundURLPolicy()


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("file:///etc/passwd", "must use HTTP or HTTPS"),
        ("https://user:password@example.com", "must not include credentials"),
        ("https://example.com:8443", "port 8443 is not allowed"),
        ("http://example.com", "unencrypted outbound HTTP is disabled"),
        ("https://example.com/path#fragment", "must not include a fragment"),
    ],
)
def test_outbound_policy_rejects_unsafe_url_syntax(url: str, message: str) -> None:
    with pytest.raises(UnsafeOutboundURLError, match=message):
        validate_outbound_url(url, policy=PUBLIC_POLICY, resolve=False)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "224.0.0.1",
        "ff02::1",
    ],
)
def test_outbound_policy_rejects_non_public_resolved_addresses(address: str) -> None:
    with pytest.raises(UnsafeOutboundURLError, match="non-public address"):
        validate_outbound_url(
            "https://service.example.com",
            policy=PUBLIC_POLICY,
            resolver=lambda _hostname, _port: [address],
        )


def test_outbound_policy_allows_public_address() -> None:
    assert validate_outbound_url(
        "https://service.example.com/path?cursor=next",
        policy=PUBLIC_POLICY,
        resolver=lambda _hostname, _port: ["93.184.216.34"],
    ) == "https://service.example.com/path?cursor=next"


def test_outbound_policy_allows_exact_operator_private_host() -> None:
    policy = OutboundURLPolicy(
        allowed_ports=frozenset({443, 8200}),
        private_host_allowlist=frozenset({"bao.internal"}),
    )

    assert validate_outbound_url(
        "https://bao.internal:8200/v1/sys/health",
        policy=policy,
        resolver=lambda _hostname, _port: ["10.0.0.10"],
    ) == "https://bao.internal:8200/v1/sys/health"


def test_outbound_policy_rejects_multicast_for_allowlisted_host() -> None:
    policy = OutboundURLPolicy(private_host_allowlist=frozenset({"service.internal"}))

    with pytest.raises(UnsafeOutboundURLError, match="non-public address"):
        validate_outbound_url(
            "https://service.internal",
            policy=policy,
            resolver=lambda _hostname, _port: ["224.0.0.1"],
        )


def test_no_redirect_handler_never_builds_redirect_request() -> None:
    request = Request("https://public.example/start")

    assert (
        NoRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://169.254.169.254/latest/meta-data",
        )
        is None
    )


def test_outbound_request_uses_no_redirect_opener(monkeypatch) -> None:
    seen_handlers = []
    response = object()

    class FakeOpener:
        def open(self, request, *, timeout):
            assert request.full_url == "https://service.example.com/start"
            assert timeout == 10
            return response

    def build_opener(*handlers):
        seen_handlers.extend(handlers)
        return FakeOpener()

    monkeypatch.setattr(outbound_http, "validate_outbound_url", lambda _url: None)
    monkeypatch.setattr(outbound_http, "build_opener", build_opener)

    result = outbound_http.open_outbound_request(
        Request("https://service.example.com/start"),
        timeout=10,
    )

    assert result is response
    assert any(isinstance(handler, NoRedirectHandler) for handler in seen_handlers)
