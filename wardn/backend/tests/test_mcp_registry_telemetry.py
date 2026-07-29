from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.mcp_registry import telemetry
from app.modules.mcp_registry.models import MCPServerVersion


def make_settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def server_version(
    *,
    hub_version_id: str | None = None,
    source_metadata: dict[str, str] | None = None,
) -> MCPServerVersion:
    hub_version_id = hub_version_id or str(uuid4())
    source_metadata = source_metadata or {
        "provider": "wardn_hub",
        "baseUrl": "https://hub.wardnai.dev",
        "sourceUrl": "https://hub.wardnai.dev/api/v1/mcp/servers",
    }
    return MCPServerVersion(
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools",
        version="1.0.0",
        server_json={
            "id": hub_version_id,
            "name": "io.github.example/weather",
            "version": "1.0.0",
            "_meta": {"wardnCatalogSource": source_metadata},
        },
        is_latest=True,
        status="active",
        status_message="",
    )


def test_mcp_server_install_telemetry_event_uses_hub_version_id() -> None:
    hub_version_id = str(uuid4())
    event = telemetry.mcp_server_install_telemetry_event(
        server_version(hub_version_id=hub_version_id),
        install_type="remote",
        settings=make_settings(app_version="v1.2.3+local"),
    )

    assert event is not None
    assert event.server_name == "io.github.example/weather"
    assert event.hub_version_id == hub_version_id
    assert event.client == "wardn-ai-remote"
    assert event.client_version == "1.2.3-local"
    assert event.url == (
        "https://hub.wardnai.dev/api/v1/mcp/servers/telemetry/"
        f"io.github.example/weather?version_id={hub_version_id}"
        "&client=wardn-ai-remote&client_version=1.2.3-local"
    )


def test_mcp_server_install_telemetry_event_uses_source_url_when_base_url_missing() -> None:
    hub_version_id = str(uuid4())
    event = telemetry.mcp_server_install_telemetry_event(
        server_version(
            hub_version_id=hub_version_id,
            source_metadata={
                "provider": "wardn_hub",
                "sourceUrl": "https://hub.wardnai.dev/api/v1/mcp/servers",
            },
        ),
        install_type="pypi",
        settings=make_settings(app_version="1.2.3"),
    )

    assert event is not None
    assert event.client == "wardn-ai-pypi"
    assert event.url.startswith(
        "https://hub.wardnai.dev/api/v1/mcp/servers/telemetry/"
    )


def test_mcp_server_install_telemetry_event_skips_when_disabled() -> None:
    event = telemetry.mcp_server_install_telemetry_event(
        server_version(),
        install_type="remote",
        settings=make_settings(telemetry=False),
    )

    assert event is None


def test_mcp_server_install_telemetry_event_skips_without_hub_version_id() -> None:
    event = telemetry.mcp_server_install_telemetry_event(
        server_version(hub_version_id="not-a-uuid"),
        install_type="remote",
        settings=make_settings(app_version="1.2.3"),
    )

    assert event is None


def test_mcp_server_install_telemetry_event_skips_non_hub_sources() -> None:
    event = telemetry.mcp_server_install_telemetry_event(
        server_version(
            source_metadata={
                "provider": "custom",
                "baseUrl": "https://registry.example.com",
            },
        ),
        install_type="remote",
        settings=make_settings(app_version="1.2.3"),
    )

    assert event is None


@pytest.mark.asyncio
async def test_record_mcp_server_install_telemetry_posts_event(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            calls.append({"read": True})
            return b""

    def open_outbound_request(request, *, timeout):
        calls.append(
            {
                "method": request.get_method(),
                "timeout": timeout,
                "url": request.full_url,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(telemetry, "open_outbound_request", open_outbound_request)
    event = telemetry.MCPServerInstallTelemetryEvent(
        url="https://hub.wardnai.dev/api/v1/mcp/servers/telemetry/io.example/server",
        server_name="io.example/server",
        version="1.0.0",
        hub_version_id=str(uuid4()),
        client="wardn-ai-remote",
        client_version="1.2.3",
    )

    await telemetry.record_mcp_server_install_telemetry(event)

    assert calls == [
        {
            "method": "POST",
            "timeout": telemetry.WARDN_HUB_TELEMETRY_TIMEOUT_SECONDS,
            "url": event.url,
        },
        {"read": True},
    ]


@pytest.mark.asyncio
async def test_record_mcp_server_install_telemetry_swallows_failures(monkeypatch) -> None:
    def open_outbound_request(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(telemetry, "open_outbound_request", open_outbound_request)
    event = telemetry.MCPServerInstallTelemetryEvent(
        url="https://hub.wardnai.dev/api/v1/mcp/servers/telemetry/io.example/server",
        server_name="io.example/server",
        version="1.0.0",
        hub_version_id=str(uuid4()),
        client="wardn-ai-remote",
        client_version="1.2.3",
    )

    await telemetry.record_mcp_server_install_telemetry(event)
