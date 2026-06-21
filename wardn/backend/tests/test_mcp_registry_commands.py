import argparse
import json

from app.commands.registry import CommandRegistry
from app.modules.mcp_registry import commands


def test_register_mcp_registry_commands_adds_sync_command() -> None:
    registry = CommandRegistry()
    commands.register_mcp_registry_commands(registry)

    parser = registry.build_parser()
    args = parser.parse_args(["syncmcpregistry"])

    assert args.command == "syncmcpregistry"
    assert args.handler == commands.handle_syncmcpregistry
    assert args.file is None
    assert args.source_url == commands.DEFAULT_REGISTRY_URL
    assert args.verbose is False


def test_register_mcp_registry_commands_adds_refresh_tools_command() -> None:
    registry = CommandRegistry()
    commands.register_mcp_registry_commands(registry)

    parser = registry.build_parser()
    args = parser.parse_args(
        ["refreshmcptools", "--server", "io.github.example/weather"]
    )

    assert args.command == "refreshmcptools"
    assert args.handler == commands.handle_refreshmcptools
    assert args.server == "io.github.example/weather"
    assert args.verbose is False


def test_register_mcp_registry_commands_adds_curated_server_command() -> None:
    registry = CommandRegistry()
    commands.register_mcp_registry_commands(registry)

    parser = registry.build_parser()
    args = parser.parse_args(["addmcpserver", "grafana"])

    assert args.command == "addmcpserver"
    assert args.handler == commands.handle_addmcpserver
    assert args.server == "grafana"
    assert args.verbose is False


def test_curated_grafana_server_uses_uvx_runtime() -> None:
    payload = commands.CURATED_SERVERS["grafana"]
    server = commands.load_supported_servers_from_payload([payload])[0]

    assert server.name == "io.github.grafana/mcp-grafana"
    assert server.packages[0]["registryType"] == "uvx"
    assert server.packages[0]["identifier"] == "mcp-grafana"
    env_names = {
        variable["name"]
        for variable in server.packages[0]["environmentVariables"]
    }
    assert {"GRAFANA_URL", "GRAFANA_SERVICE_ACCOUNT_TOKEN"} <= env_names


def test_load_supported_servers_reads_curated_file(tmp_path) -> None:
    path = tmp_path / "supported_servers.json"
    path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "$schema": (
                            "https://static.modelcontextprotocol.io/schemas/"
                            "2025-12-11/server.schema.json"
                        ),
                        "name": "io.github.example/weather",
                        "description": "Weather tools for forecasts",
                        "version": "1.0.0",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    servers = commands.load_supported_servers(path)

    assert len(servers) == 1
    assert servers[0].name == "io.github.example/weather"


def test_load_supported_servers_reads_official_registry_payload() -> None:
    payload = {
        "servers": [
            {
                "server": {
                    "$schema": (
                        "https://static.modelcontextprotocol.io/schemas/"
                        "2025-12-11/server.schema.json"
                    ),
                    "name": "io.github.example/weather",
                    "description": "Weather tools for forecasts",
                    "title": "Weather",
                    "version": "1.0.0",
                },
                "_meta": {
                    "io.modelcontextprotocol.registry/official": {
                        "status": "active",
                        "statusChangedAt": "2026-06-21T00:00:00Z",
                        "publishedAt": "2026-06-21T00:00:00Z",
                        "updatedAt": "2026-06-21T00:00:00Z",
                        "isLatest": True,
                    }
                },
            }
        ],
        "metadata": {"count": 1},
    }

    servers = commands.load_supported_servers_from_payload(payload)

    assert len(servers) == 1
    assert servers[0].name == "io.github.example/weather"
    assert (
        servers[0].meta["io.modelcontextprotocol.registry/official"]["isLatest"] is True
    )


def test_url_with_query_params_preserves_existing_query() -> None:
    url = commands.url_with_query_params(
        "https://registry.modelcontextprotocol.io/v0/servers?limit=25",
        cursor="io.github.example/weather:1.0.0",
        limit=100,
    )

    assert url == (
        "https://registry.modelcontextprotocol.io/v0/servers?"
        "limit=25&cursor=io.github.example%2Fweather%3A1.0.0"
    )


def test_load_supported_servers_from_registry_url_follows_cursor(monkeypatch) -> None:
    calls = []
    timestamps = {
        "statusChangedAt": "2026-06-21T00:00:00Z",
        "publishedAt": "2026-06-21T00:00:00Z",
        "updatedAt": "2026-06-21T00:00:00Z",
    }

    def page(name: str, version: str, *, next_cursor: str = "", latest: bool = True):
        return {
            "servers": [
                {
                    "server": {
                        "$schema": (
                            "https://static.modelcontextprotocol.io/schemas/"
                            "2025-12-11/server.schema.json"
                        ),
                        "name": name,
                        "description": "Weather tools for forecasts",
                        "title": "Weather",
                        "version": version,
                    },
                    "_meta": {
                        "io.modelcontextprotocol.registry/official": {
                            "status": "active",
                            "isLatest": latest,
                            **timestamps,
                        }
                    },
                }
            ],
            "metadata": {"count": 1, "nextCursor": next_cursor},
        }

    payloads = [
        page("io.github.example/weather", "1.0.0", next_cursor="next", latest=False),
        page("io.github.example/weather", "1.1.0", latest=True),
    ]

    def fetch(url: str):
        calls.append(url)
        return payloads.pop(0)

    monkeypatch.setattr(commands, "fetch_registry_payload", fetch)

    servers = commands.load_supported_servers_from_registry_url(
        "https://registry.modelcontextprotocol.io/v0/servers",
        limit=1,
        max_pages=None,
    )

    assert [server.version for server in servers] == ["1.0.0", "1.1.0"]
    assert calls == [
        "https://registry.modelcontextprotocol.io/v0/servers?limit=1",
        "https://registry.modelcontextprotocol.io/v0/servers?limit=1&cursor=next",
    ]


def test_handle_syncmcpregistry_reports_missing_file(capsys) -> None:
    result = commands.handle_syncmcpregistry(
        argparse.Namespace(
            file="/tmp/wardn-missing-supported-servers.json",
            source_url=commands.DEFAULT_REGISTRY_URL,
            limit=commands.DEFAULT_REGISTRY_LIMIT,
            max_pages=None,
            dry_run=False,
            verbose=False,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Error:" in captured.err
