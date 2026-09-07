"""Initialize/unseal the local Compose OpenBao and provision Wardn's AppRole.

Recovery material stays in an owner-only local file, outside the container's
encrypted data volume. It is never printed or mounted into Wardn.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = """path "secret/data/wardn/*" {
  capabilities = ["create", "read", "update", "delete"]
}
path "secret/metadata/wardn/*" {
  capabilities = ["read", "list", "delete"]
}
"""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalOpenBao:
    def __init__(self, url: str):
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Setup requires the local Compose HTTP address on loopback")
        self.url = url.rstrip("/")
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())

    def request(self, method: str, path: str, payload=None, *, token: str = "") -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Vault-Token"] = token
        request = urllib.request.Request(
            f"{self.url}/v1/{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self.client.open(request, timeout=15) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            # Do not surface response bodies or request credentials in errors.
            raise RuntimeError(f"OpenBao {method} {path} returned HTTP {exc.code}") from None


def write_private(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(payload)
        file.flush()
        os.fsync(file.fileno())


def setup(url: str, state_dir: Path, credentials_dir: Path) -> None:
    client = LocalOpenBao(url)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    state_path = state_dir / "bootstrap.json"
    status = client.request("GET", "sys/seal-status")

    if not status["initialized"]:
        # An existing recovery file belongs to another/previous volume. Never
        # replace it implicitly when a database volume is removed or changed.
        with os.fdopen(
            os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as file:
            recovery = client.request(
                "POST", "sys/init", {"secret_shares": 1, "secret_threshold": 1}
            )
            json.dump(recovery, file)
            file.flush()
            os.fsync(file.fileno())
    else:
        if not state_path.is_file():
            raise RuntimeError(
                "OpenBao is already initialized; restore its recovery file or use manual setup"
            )
        recovery = json.loads(state_path.read_text())
        state_path.chmod(0o600)

    if status["sealed"]:
        result = client.request("POST", "sys/unseal", {"key": recovery["keys_base64"][0]})
        if result["sealed"]:
            raise RuntimeError("OpenBao is still sealed; check that the recovery file matches")

    for _ in range(30):
        health = client.request("GET", "sys/health?standbyok=true&standbycode=200&sealedcode=200")
        if not health["sealed"] and not health["standby"]:
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("OpenBao did not become active after unsealing")

    token = recovery["root_token"]
    mounts = client.request("GET", "sys/mounts", token=token)["data"]
    if "secret/" not in mounts:
        client.request(
            "POST", "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}}, token=token
        )
    elif (
        mounts["secret/"]["type"] != "kv"
        or mounts["secret/"].get("options", {}).get("version") != "2"
    ):
        raise RuntimeError("Existing secret/ mount is not KV v2; it was left unchanged")

    auth = client.request("GET", "sys/auth", token=token)["data"]
    if "approle/" not in auth:
        client.request("POST", "sys/auth/approle", {"type": "approle"}, token=token)
    elif auth["approle/"]["type"] != "approle":
        raise RuntimeError("Existing approle/ mount has a different authentication method")

    client.request("PUT", "sys/policies/acl/wardn-compose", {"policy": POLICY}, token=token)
    client.request(
        "POST",
        "auth/approle/role/wardn-compose",
        {"token_policies": ["wardn-compose"], "token_ttl": "1h", "token_max_ttl": "24h"},
        token=token,
    )
    role_id = client.request("GET", "auth/approle/role/wardn-compose/role-id", token=token)["data"][
        "role_id"
    ]
    credentials_dir.mkdir(parents=True, exist_ok=True)
    role_file = credentials_dir / "role_id"
    secret_file = credentials_dir / "secret_id"
    if not (
        role_file.is_file() and secret_file.is_file() and role_file.read_text().strip() == role_id
    ):
        secret_id = client.request(
            "POST", "auth/approle/role/wardn-compose/secret-id", {}, token=token
        )["data"]["secret_id"]
        write_private(role_file, role_id + "\n")
        write_private(secret_file, secret_id + "\n")
    else:
        role_file.chmod(0o600)
        secret_file.chmod(0o600)

    # Prove the issued role can sign in without exposing its token.
    login = client.request(
        "POST",
        "auth/approle/login",
        {"role_id": role_id, "secret_id": secret_file.read_text().strip()},
    )
    app_token = login["auth"]["client_token"]
    probe = f"wardn/compose-setup/{uuid.uuid4().hex}"
    try:
        client.request("POST", f"secret/data/{probe}", {"data": {"probe": "ok"}}, token=app_token)
        result = client.request("GET", f"secret/data/{probe}", token=app_token)
        if result["data"]["data"] != {"probe": "ok"}:
            raise RuntimeError("AppRole KV verification failed")
        client.request("DELETE", f"secret/metadata/{probe}", token=app_token)
    finally:
        client.request("POST", "auth/token/revoke-self", {}, token=app_token)
    print("OpenBao is initialized, unsealed, and Wardn's AppRole is ready.")
    print(f"Recovery material: {state_path} (mode 0600); keep a secure backup.")
    print("Wardn secret backend: base URL http://openbao:8200, auth profile compose.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8200")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "data/openbao")
    parser.add_argument("--credentials-dir", type=Path, default=ROOT / "infra/compose/openbao/auth")
    args = parser.parse_args()
    try:
        setup(args.url, args.state_dir, args.credentials_dir)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"OpenBao setup failed: {exc}", file=sys.stderr)
        sys.exit(1)
