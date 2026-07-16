import ipaddress
import socket
import ssl
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from app.core.config import Settings, get_settings

AddressResolver = Callable[[str, int], Iterable[str]]


class UnsafeOutboundURLError(ValueError):
    pass


@dataclass(frozen=True)
class OutboundURLPolicy:
    allow_http: bool = False
    allowed_ports: frozenset[int] = frozenset({443})
    private_host_allowlist: frozenset[str] = frozenset()

    @classmethod
    def from_settings(cls, settings: Settings) -> "OutboundURLPolicy":
        return cls(
            allow_http=settings.outbound_http_allow_http,
            allowed_ports=frozenset(settings.outbound_http_allowed_ports),
            private_host_allowlist=frozenset(
                normalize_hostname(host)
                for host in settings.outbound_http_private_host_allowlist
            ),
        )


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_hostname(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise UnsafeOutboundURLError("outbound URL hostname is invalid") from exc


def resolved_addresses(hostname: str, port: int) -> set[str]:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            results = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            raise UnsafeOutboundURLError("outbound URL hostname could not be resolved") from exc
        addresses = {str(result[4][0]).split("%", maxsplit=1)[0] for result in results}
        if not addresses:
            raise UnsafeOutboundURLError(
                "outbound URL hostname resolved to no addresses"
            ) from None
        return addresses
    return {str(address)}


def normalized_ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_public_address(value: str) -> bool:
    address = normalized_ip_address(value)
    return address.is_global and not address.is_multicast and not address.is_unspecified


def is_usable_private_address(value: str) -> bool:
    address = normalized_ip_address(value)
    return not address.is_multicast and not address.is_unspecified


def validate_outbound_url(
    url: str,
    *,
    policy: OutboundURLPolicy | None = None,
    resolver: AddressResolver | None = None,
    resolve: bool = True,
) -> str:
    policy = policy or OutboundURLPolicy.from_settings(get_settings())
    value = url.strip()
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        raise UnsafeOutboundURLError(
            "outbound URL must not contain whitespace or control characters"
        )
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeOutboundURLError("outbound URL must use HTTP or HTTPS")
    if parsed.scheme == "http" and not policy.allow_http:
        raise UnsafeOutboundURLError("unencrypted outbound HTTP is disabled")
    if not parsed.netloc or not parsed.hostname:
        raise UnsafeOutboundURLError("outbound URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeOutboundURLError("outbound URL must not include credentials")
    if parsed.fragment:
        raise UnsafeOutboundURLError("outbound URL must not include a fragment")
    if "\\" in parsed.netloc or "%" in parsed.hostname:
        raise UnsafeOutboundURLError("outbound URL authority is invalid")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeOutboundURLError("outbound URL port is invalid") from exc
    if port not in policy.allowed_ports:
        raise UnsafeOutboundURLError(f"outbound URL port {port} is not allowed")

    hostname = normalize_hostname(parsed.hostname)
    if not resolve:
        return value
    addresses = set((resolver or resolved_addresses)(hostname, port))
    if not addresses:
        raise UnsafeOutboundURLError("outbound URL hostname resolved to no addresses")
    try:
        if hostname in policy.private_host_allowlist:
            unsafe_addresses = sorted(
                address for address in addresses if not is_usable_private_address(address)
            )
        else:
            unsafe_addresses = sorted(
                address for address in addresses if not is_public_address(address)
            )
    except ValueError as exc:
        raise UnsafeOutboundURLError("outbound URL hostname resolved incorrectly") from exc
    if unsafe_addresses:
        raise UnsafeOutboundURLError("outbound URL resolves to a non-public address")
    return value


def open_outbound_request(
    request: Request,
    *,
    timeout: float,
    context: ssl.SSLContext | None = None,
) -> Any:
    validate_outbound_url(request.full_url)
    handlers: list[Any] = [NoRedirectHandler()]
    if context is not None:
        handlers.append(HTTPSHandler(context=context))
    return build_opener(*handlers).open(request, timeout=timeout)
