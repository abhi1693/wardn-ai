import argparse
import json
import logging

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
    assert args.source == "official"
    assert args.api_key is None
    assert args.tenant_id is None
    assert args.latest_only is False
    assert args.readme_descriptions is False
    assert args.verbose is False


def test_register_mcp_registry_commands_adds_pulsemcp_sync_options() -> None:
    registry = CommandRegistry()
    commands.register_mcp_registry_commands(registry)

    parser = registry.build_parser()
    args = parser.parse_args(
        [
            "syncmcpregistry",
            "--source",
            "pulsemcp",
            "--api-key",
            "secret-key",
            "--tenant-id",
            "tenant-1",
            "--latest-only",
            "--readme-descriptions",
            "--github-token",
            "github-secret",
            "--updated-since",
            "2026-06-22T00:00:00Z",
        ]
    )

    assert args.source == "pulsemcp"
    assert args.api_key == "secret-key"
    assert args.tenant_id == "tenant-1"
    assert args.latest_only is True
    assert args.readme_descriptions is True
    assert args.github_token == "github-secret"
    assert args.updated_since == "2026-06-22T00:00:00Z"


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


def test_load_supported_servers_reads_pulsemcp_registry_payload() -> None:
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
                    "com.pulsemcp/server": {
                        "visitorsEstimateMostRecentWeek": 1250,
                        "isOfficial": True,
                    },
                    "com.pulsemcp/server-version": {
                        "source": "registry.modelcontextprotocol.io",
                        "status": "active",
                        "publishedAt": "2026-06-21T00:00:00Z",
                        "updatedAt": "2026-06-22T00:00:00Z",
                        "isLatest": True,
                    },
                },
            }
        ],
        "metadata": {"count": 1},
    }

    servers = commands.load_supported_servers_from_payload(payload)

    assert len(servers) == 1
    assert servers[0].name == "io.github.example/weather"
    assert servers[0].meta["com.pulsemcp/server"]["isOfficial"] is True
    assert servers[0].meta["com.pulsemcp/server-version"]["isLatest"] is True


def test_registry_url_loader_strips_unsupported_mcpb_packages(monkeypatch) -> None:
    payload = {
        "servers": [
            {
                "server": {
                    "$schema": (
                        "https://static.modelcontextprotocol.io/schemas/"
                        "2025-12-11/server.schema.json"
                    ),
                    "name": "io.github.example/bundle",
                    "description": "Server with an unsupported MCPB package target",
                    "title": "Bundle",
                    "version": "1.0.0",
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@example/bundle-mcp",
                            "version": "1.0.0",
                            "transport": {"type": "stdio"},
                        },
                        {
                            "registryType": "mcpb",
                            "identifier": "example.mcpb",
                            "version": "1.0.0",
                        },
                    ],
                },
            }
        ],
        "metadata": {"count": 1},
    }

    monkeypatch.setattr(commands, "fetch_registry_payload", lambda url: payload)

    servers = commands.load_supported_servers_from_registry_url(
        "https://registry.modelcontextprotocol.io/v0/servers",
        limit=100,
        max_pages=1,
    )

    assert len(servers) == 1
    assert servers[0].packages == [
        {
            "registryType": "npm",
            "identifier": "@example/bundle-mcp",
            "version": "1.0.0",
            "transport": {"type": "stdio"},
        }
    ]


def test_registry_url_loader_sanitizes_invalid_source_urls(monkeypatch) -> None:
    payload = {
        "servers": [
            {
                "server": {
                    "$schema": (
                        "https://static.modelcontextprotocol.io/schemas/"
                        "2025-12-11/server.schema.json"
                    ),
                    "name": "io.github.example/links",
                    "description": "Server with mixed link quality",
                    "title": "Links",
                    "version": "1.0.0",
                    "websiteUrl": "not-a-url",
                    "repository": {
                        "source": "github",
                        "url": "https://github.com/example/links",
                    },
                    "icons": [
                        {"src": "https://example.com/icon.png"},
                        {"src": "https://bad url/icon.png"},
                    ],
                    "remotes": [
                        {"type": "streamable-http", "url": "https://example.com/mcp"},
                        {"type": "sse", "url": "not-a-url"},
                    ],
                    "_meta": {
                        "io.modelcontextprotocol.registry/publisher-provided": {
                            "docs": "https://example.com/docs",
                            "connect": "javascript:alert(1)",
                        }
                    },
                },
            }
        ],
        "metadata": {"count": 1},
    }

    monkeypatch.setattr(commands, "fetch_registry_payload", lambda url: payload)

    servers = commands.load_supported_servers_from_registry_url(
        "https://registry.modelcontextprotocol.io/v0/servers",
        limit=100,
        max_pages=1,
    )

    assert len(servers) == 1
    assert servers[0].website_url == ""
    assert servers[0].repository == {
        "source": "github",
        "url": "https://github.com/example/links",
    }
    assert servers[0].icons == [{"src": "https://example.com/icon.png"}]
    assert servers[0].remotes == [
        {"type": "streamable-http", "url": "https://example.com/mcp"}
    ]
    assert servers[0].meta["io.modelcontextprotocol.registry/publisher-provided"] == {
        "docs": "https://example.com/docs",
    }


def test_registry_url_loader_removes_invalid_repository_url(monkeypatch) -> None:
    payload = {
        "servers": [
            {
                "server": {
                    "$schema": (
                        "https://static.modelcontextprotocol.io/schemas/"
                        "2025-12-11/server.schema.json"
                    ),
                    "name": "io.github.example/bad-repo",
                    "description": "Server with an invalid repository URL",
                    "title": "Bad Repo",
                    "version": "1.0.0",
                    "repository": {
                        "source": "github",
                        "url": "https://bad repo.example.com/project",
                    },
                },
            }
        ],
        "metadata": {"count": 1},
    }

    monkeypatch.setattr(commands, "fetch_registry_payload", lambda url: payload)

    servers = commands.load_supported_servers_from_registry_url(
        "https://registry.modelcontextprotocol.io/v0/servers",
        limit=100,
        max_pages=1,
    )

    assert len(servers) == 1
    assert servers[0].repository == {"source": "github"}


def test_github_repo_from_url_parses_repository_urls() -> None:
    assert commands.github_repo_from_url("https://github.com/example/weather") == (
        "example",
        "weather",
    )
    assert commands.github_repo_from_url("https://github.com/example/weather.git") == (
        "example",
        "weather",
    )
    assert commands.github_repo_from_url(
        "https://github.com/example/weather/tree/main/packages/server"
    ) == ("example", "weather")
    assert commands.github_repo_from_url("https://gitlab.com/example/weather") is None
    assert commands.github_repo_from_url("https://github.com/example/bad repo") is None


def test_enrich_server_description_from_readme_uses_github_readme(monkeypatch) -> None:
    calls = []

    def fetch_readme(owner: str, repo: str, **kwargs):
        calls.append((owner, repo, kwargs["github_token"]))
        return "# Weather MCP\n\nDetailed README content."

    monkeypatch.setattr(commands, "fetch_github_readme", fetch_readme)
    server = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "description": "Short description",
        "version": "1.0.0",
        "repository": {
            "source": "github",
            "url": "https://github.com/example/weather",
        },
    }
    cache = {}

    enriched = commands.enrich_server_description_from_readme(
        server,
        readme_cache=cache,
        github_token="token",
    )
    enriched_again = commands.enrich_server_description_from_readme(
        server,
        readme_cache=cache,
        github_token="token",
    )

    assert enriched["description"] == "# Weather MCP\n\nDetailed README content."
    assert enriched_again["description"] == "# Weather MCP\n\nDetailed README content."
    assert calls == [("example", "weather", "token")]


def test_registry_url_loader_can_use_readmes_as_descriptions(monkeypatch) -> None:
    payload = {
        "servers": [
            {
                "server": {
                    "$schema": (
                        "https://static.modelcontextprotocol.io/schemas/"
                        "2025-12-11/server.schema.json"
                    ),
                    "name": "io.github.example/weather",
                    "description": "Short weather description",
                    "title": "Weather",
                    "version": "1.0.0",
                    "repository": {
                        "source": "github",
                        "url": "https://github.com/example/weather",
                    },
                },
            }
        ],
        "metadata": {"count": 1},
    }

    monkeypatch.setattr(commands, "fetch_registry_payload", lambda url: payload)
    monkeypatch.setattr(
        commands,
        "fetch_github_readme",
        lambda owner, repo, **kwargs: "README description",
    )

    servers = commands.load_supported_servers_from_registry_url(
        "https://registry.modelcontextprotocol.io/v0/servers",
        limit=100,
        max_pages=1,
        readme_descriptions=True,
    )

    assert len(servers) == 1
    assert servers[0].description == "README description"


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


def test_url_with_query_params_adds_incremental_and_latest_params() -> None:
    url = commands.url_with_query_params(
        "https://api.pulsemcp.com/v0.1/servers",
        limit=100,
        updated_since="2026-06-22T00:00:00Z",
        version="latest",
    )

    assert url == (
        "https://api.pulsemcp.com/v0.1/servers?"
        "limit=100&updated_since=2026-06-22T00%3A00%3A00Z&version=latest"
    )


def test_pulsemcp_registry_source_uses_default_url_and_auth_headers() -> None:
    assert (
        commands.registry_source_url("pulsemcp", commands.DEFAULT_REGISTRY_URL)
        == commands.PULSE_REGISTRY_URL
    )
    assert commands.registry_headers(
        "pulsemcp",
        api_key="secret-key",
        tenant_id="tenant-1",
    ) == {
        "X-API-Key": "secret-key",
        "X-Tenant-ID": "tenant-1",
    }


def test_load_supported_servers_from_registry_url_follows_cursor(monkeypatch, caplog) -> None:
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
    caplog.set_level(logging.DEBUG, logger=commands.logger.name)

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
    assert "1 unique in fetch, 0 repeated in fetch" in caplog.text
    assert " new, " not in caplog.text


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
