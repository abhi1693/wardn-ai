"""Check Compose deployment contracts without reading local credentials."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def render(values: dict[str, str], *, build: bool = False) -> dict:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("WARDN_", "NEXT_PUBLIC_", "COMPOSE_", "POSTGRES_"))
    }
    with tempfile.TemporaryDirectory() as directory:
        env_file = Path(directory) / ".env"
        env_file.write_text(
            "".join(f"{key}={value}\n" for key, value in values.items())
        )
        command = [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            "compose.yaml",
        ]
        if build:
            command += ["-f", "compose.build.yaml"]
        result = subprocess.run(
            [*command, "config", "--format", "json"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode:
        raise ValueError("Compose fixture rejected; configuration output withheld")
    return json.loads(result.stdout)


def check() -> None:
    secrets = {
        "POSTGRES_PASSWORD": "a" * 64,
        "WARDN_API_TOKEN_SECRET": "b" * 64,
        "WARDN_SESSION_SECRET": "c" * 64,
    }
    for required in secrets:
        try:
            render({**secrets, required: ""})
        except ValueError:
            pass
        else:
            raise AssertionError(f"Missing required credential accepted: {required}")

    default = render(secrets)
    assert default["networks"]["data"]["internal"]
    assert default["services"]["proxy"]["ports"][0]["host_ip"] == "0.0.0.0"
    for bind in ("127.0.0.1", "::1"):
        custom = render({**secrets, "WARDN_BIND_IP": bind, "WARDN_PORT": "3101"})
        services = custom["services"]
        assert services["proxy"]["ports"][0]["host_ip"] == bind
        assert services["proxy"]["ports"][0]["published"] == "3101"
        assert (
            services["api"]["environment"]["WARDN_PUBLIC_BASE_URL"]
            == "http://localhost:3101"
        )

    options = {
        "WARDN_PUBLIC_BASE_URL": "https://wardn.example.com",
        "WARDN_AUTH_MODE": "oidc",
        "WARDN_OIDC_ISSUER_URL": "https://identity.example.com",
        "WARDN_OIDC_CLIENT_ID": "compose-check",
        "WARDN_OIDC_CLIENT_SECRET": "test-oidc-secret",
        "WARDN_SESSION_COOKIE_NAME": "custom_session",
        "WARDN_OUTBOUND_HTTP_ALLOW_HTTP": "true",
        "WARDN_OUTBOUND_HTTP_PRIVATE_HOST_ALLOWLIST": "host.docker.internal",
        "WARDN_DATABASE_URL": "postgresql+asyncpg://external@database.example/test",
        "WARDN_GITHUB_TOKEN": "test-github-token",
    }
    for build in (False, True):
        config = render({**secrets, **options}, build=build)
        services = config["services"]
        assert services["postgres"]["networks"] == {"data": None}
        for name, service in services.items():
            assert bool(service.get("ports")) == (name == "proxy"), name
            assert not service.get("privileged"), name
            if name != "postgres":
                assert service["read_only"], name
                assert service["cap_drop"] == ["ALL"], name
            for volume in service.get("volumes", []):
                assert "docker.sock" not in volume["target"]

        for name in ("api", "worker", "migrate"):
            service = services[name]
            environment = service["environment"]
            assert all(environment[key] == value for key, value in options.items()), (
                name
            )
            assert (
                environment["WARDN_FRONTEND_BASE_URL"]
                == options["WARDN_PUBLIC_BASE_URL"]
            )
            assert "host.docker.internal=host-gateway" in service["extra_hosts"]
            assert service["volumes"][0]["source"] == "mcp-installations"
            if name != "migrate":
                assert (
                    service["depends_on"]["migrate"]["condition"]
                    == "service_completed_successfully"
                )
            if build:
                assert service["build"]["target"] == "worker"
            else:
                assert "build" not in service
        assert services["migrate"]["restart"] == "no"
        frontend_environment = services["frontend"]["environment"]
        assert set(frontend_environment) == {
            "HOSTNAME",
            "WARDN_BACKEND_URL",
            "NEXT_PUBLIC_SITE_URL",
            "WARDN_SESSION_COOKIE_NAME",
        }
        assert frontend_environment["WARDN_BACKEND_URL"] == "http://api:8000"
        assert (
            frontend_environment["NEXT_PUBLIC_SITE_URL"]
            == options["WARDN_PUBLIC_BASE_URL"]
        )
        assert services["frontend"]["networks"] == {"default": None}
        assert services["proxy"]["networks"] == {"default": None}

    images = {
        "WARDN_WORKER_IMAGE": "registry.example/worker@sha256:" + "a" * 64,
        "WARDN_FRONTEND_IMAGE": "registry.example/frontend:release",
    }
    services = render({**secrets, **images})["services"]
    assert all(
        services[name]["image"] == images["WARDN_WORKER_IMAGE"]
        for name in ("api", "worker", "migrate")
    )
    assert services["frontend"]["image"] == images["WARDN_FRONTEND_IMAGE"]
    print(
        "Compose checks passed: credentials, migration gating, networking, "
        "overrides and local builds"
    )


if __name__ == "__main__":
    check()
