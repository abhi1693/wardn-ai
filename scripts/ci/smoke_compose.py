"""Exercise an EMPTY disposable Compose instance through its published proxy."""

import argparse
import base64
import http.client
import http.cookiejar
import json
import secrets
import urllib.parse
import urllib.request


def check(base_url: str) -> None:
    cookies = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))

    def request(path: str, *, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        with client.open(req, timeout=30) as response:
            if path == "/org":
                assert response.geturl() == f"{base_url}/org", (
                    "Authenticated page redirected"
                )
            return response.status, response.read()

    assert json.loads(request("/api/v1/health/ready")[1])["status"] == "ready"
    assert b"<html" in request("/login")[1]
    assert b"__WARDN_API_BASE_URL__" in request("/wardn-config.js")[1]
    assert json.loads(request("/api/v1/auth/config")[1])["localLoginEnabled"]

    account = {"email": "compose-smoke@example.com", "password": secrets.token_hex(32)}
    # Refuse existing databases: bootstrap returns 409 when any user exists.
    status, created = request("/api/v1/users/bootstrap", payload=account)
    assert status == 201
    user_id = json.loads(created)["id"]
    assert (
        json.loads(request("/api/v1/auth/login", payload=account)[1])["id"] == user_id
    )
    assert any(cookie.name == "wardn_session" for cookie in cookies)
    assert json.loads(request("/api/v1/auth/me")[1])["id"] == user_id
    # A server-rendered authenticated page must retain the cookie across both hops.
    assert b"<html" in request("/org")[1]

    # Even an unknown WebSocket route should reach Starlette's handshake denial,
    # not Next.js or a proxy error. No production-only chat route is assumed.
    url = urllib.parse.urlsplit(base_url)
    connection_type = (
        http.client.HTTPSConnection
        if url.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_type(url.hostname, url.port, timeout=10)
    connection.request(
        "GET",
        "/api/v1/compose-smoke-websocket",
        headers={
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": base64.b64encode(secrets.token_bytes(16)).decode(),
        },
    )
    try:
        response = connection.getresponse()
        assert response.status == 403, response.status
    finally:
        connection.close()
    print(
        "Compose smoke passed: readiness, UI, bootstrap, login, session/SSR and WebSocket routing"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "base_url", help="Published URL of an empty disposable Compose instance"
    )
    check(parser.parse_args().base_url.rstrip("/"))
