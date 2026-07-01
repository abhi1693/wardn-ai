import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandRegistry
from app.db.session import AsyncSessionLocal
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry.schemas import MCPServerCreate
from app.modules.mcp_registry.service import sync_supported_servers
from app.modules.mcp_registry.tool_service import refresh_tool_schemas

DEFAULT_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
PULSE_REGISTRY_URL = "https://api.pulsemcp.com/v0.1/servers"
WARDN_HUB_CATALOG_PATH = "/api/v1/mcp/catalog"
DEFAULT_REGISTRY_LIMIT = 100
PROGRESS_PAGE_INTERVAL = 10
REGISTRY_SYNC_USER_AGENT = "Wardn/0.1 (+https://wardnai.dev)"
CURATED_SERVERS = {
    "grafana": {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.grafana/mcp-grafana",
        "title": "Grafana",
        "description": (
            "MCP server for querying and managing Grafana dashboards, datasources, "
            "alerts, annotations, incidents, and observability data."
        ),
        "version": "latest",
        "websiteUrl": "https://github.com/grafana/mcp-grafana",
        "repository": {
            "source": "github",
            "url": "https://github.com/grafana/mcp-grafana",
        },
        "packages": [
            {
                "registryType": "uvx",
                "identifier": "mcp-grafana",
                "version": "latest",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {
                        "name": "GRAFANA_URL",
                        "format": "string",
                        "isRequired": True,
                        "description": "Grafana instance URL, for example https://myinstance.grafana.net.",
                    },
                    {
                        "name": "GRAFANA_SERVICE_ACCOUNT_TOKEN",
                        "format": "string",
                        "isRequired": True,
                        "isSecret": True,
                        "description": (
                            "Grafana service account token. Use "
                            "GRAFANA_SERVICE_ACCOUNT_TOKEN instead of deprecated "
                            "GRAFANA_API_KEY."
                        ),
                    },
                    {
                        "name": "GRAFANA_ORG_ID",
                        "format": "string",
                        "description": "Optional Grafana organization ID for multi-org instances.",
                    },
                    {
                        "name": "GRAFANA_EXTRA_HEADERS",
                        "format": "string",
                        "description": (
                            "Optional JSON object of extra headers sent to Grafana API "
                            "requests."
                        ),
                    },
                ],
            }
        ],
        "remotes": [],
        "icons": [],
    },
}
logger = logging.getLogger(__name__)


def configure_syncmcpregistry_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--file",
        default=None,
        help="Path to a JSON file containing supported MCP server definitions.",
    )
    parser.add_argument(
        "--source-url",
        default=DEFAULT_REGISTRY_URL,
        help="MCP registry servers endpoint to sync from.",
    )
    parser.add_argument(
        "--source",
        choices=("official", "pulsemcp", "custom"),
        default="official",
        help="Registry source type. Use pulsemcp to apply PulseMCP defaults and auth headers.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "API key for authenticated registry sources such as PulseMCP. "
            "Defaults to WARDN_PULSEMCP_API_KEY."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Tenant ID for PulseMCP. Defaults to WARDN_PULSEMCP_TENANT_ID.",
    )
    parser.add_argument(
        "--organization-id",
        default=None,
        help="Organization UUID to sync into. Defaults to Wardn's default organization.",
    )
    parser.add_argument(
        "--updated-since",
        default=None,
        help="RFC3339 timestamp for incremental registry sync.",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Request only each server's latest version with version=latest.",
    )
    parser.add_argument(
        "--readme-descriptions",
        action="store_true",
        help="Use GitHub repository README content as synced server descriptions.",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help=(
            "GitHub token for README enrichment. "
            "Defaults to WARDN_GITHUB_TOKEN or GITHUB_TOKEN."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_REGISTRY_LIMIT,
        help="Number of server versions to request per registry page.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of registry pages to fetch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and validate server entries without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show page-level registry sync details.",
    )


def configure_refreshmcptools_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--server",
        required=True,
        help="Canonical enabled MCP server name to refresh tools for.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed refresh logs.",
    )


def configure_addmcpserver_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "server",
        choices=sorted(CURATED_SERVERS),
        help="Curated supported MCP server to add.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed add logs.",
    )


def configure_command_logging(*, verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def _server_documents_from_payload(payload) -> list[dict]:
    if isinstance(payload, list):
        servers = payload
    else:
        servers = payload.get("servers", [])

    documents = []
    for item in servers:
        if isinstance(item, dict) and isinstance(item.get("server"), dict):
            server = dict(item["server"])
            metadata = item.get("_meta")
            if isinstance(metadata, dict):
                server_metadata = server.get("_meta")
                merged_metadata = dict(server_metadata) if isinstance(server_metadata, dict) else {}
                merged_metadata.update(metadata)
                server["_meta"] = merged_metadata
            documents.append(server)
        elif isinstance(item, dict) and isinstance(item.get("versions"), list):
            documents.extend(_wardn_hub_catalog_documents(item))
        else:
            documents.append(item)

    return documents


def _wardn_hub_catalog_documents(server: dict) -> list[dict]:
    documents = []
    for version in server["versions"]:
        if not isinstance(version, dict):
            continue
        server_json = version.get("serverJson")
        document = dict(server_json) if isinstance(server_json, dict) else {}
        document.setdefault(
            "$schema",
            "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        )
        for key in (
            "name",
            "title",
            "description",
            "documentation",
            "websiteUrl",
            "repository",
            "icons",
        ):
            if key not in document and key in server:
                document[key] = server[key]
        document["version"] = str(version.get("version") or document.get("version") or "").strip()
        document["packages"] = version.get("packages", document.get("packages", [])) or []
        document["remotes"] = version.get("remotes", document.get("remotes", [])) or []
        metadata = dict(document.get("_meta") or {})
        metadata["io.modelcontextprotocol.registry/official"] = {
            "status": version.get("status") or "active",
            "statusMessage": version.get("statusMessage") or "",
            "statusChangedAt": version.get("statusChangedAt") or version.get("updatedAt"),
            "publishedAt": version.get("publishedAt") or version.get("createdAt"),
            "updatedAt": version.get("updatedAt") or version.get("publishedAt"),
            "isLatest": bool(version.get("isLatest")),
        }
        metadata["dev.wardnai.hub/catalog"] = {
            "qualityScore": version.get("qualityScore"),
            "trustReport": version.get("trustReport"),
        }
        document["_meta"] = metadata
        documents.append(document)
    return documents


def strip_unsupported_package_targets(server: dict) -> dict:
    packages = server.get("packages")
    if not isinstance(packages, list):
        return server

    supported_packages = [
        package
        for package in packages
        if not (
            isinstance(package, dict)
            and str(package.get("registryType") or "").casefold() == "mcpb"
        )
    ]
    if len(supported_packages) == len(packages):
        return server

    sanitized = dict(server)
    sanitized["packages"] = supported_packages
    return sanitized


def is_valid_http_url(value: str) -> bool:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        return False
    split_url = urlsplit(value)
    return split_url.scheme in {"http", "https"} and bool(split_url.netloc)


def sanitized_url_value(value) -> str:
    return value if isinstance(value, str) and is_valid_http_url(value) else ""


def sanitize_publisher_links(meta) -> dict | None:
    if not isinstance(meta, dict):
        return meta

    sanitized = dict(meta)
    publisher = sanitized.get("io.modelcontextprotocol.registry/publisher-provided")
    if isinstance(publisher, dict):
        sanitized_publisher = dict(publisher)
        for key in ("docs", "connect"):
            value = sanitized_publisher.get(key)
            if isinstance(value, str) and not is_valid_http_url(value):
                sanitized_publisher.pop(key, None)
        sanitized["io.modelcontextprotocol.registry/publisher-provided"] = sanitized_publisher
    return sanitized


def sanitize_source_urls(server: dict) -> dict:
    sanitized = dict(server)

    website_url = sanitized.get("websiteUrl")
    if isinstance(website_url, str):
        sanitized["websiteUrl"] = sanitized_url_value(website_url)

    repository = sanitized.get("repository")
    if isinstance(repository, dict):
        sanitized_repository = dict(repository)
        url = sanitized_repository.get("url")
        if isinstance(url, str) and not is_valid_http_url(url):
            sanitized_repository.pop("url", None)
        sanitized["repository"] = sanitized_repository

    icons = sanitized.get("icons")
    if isinstance(icons, list):
        sanitized["icons"] = [
            icon
            for icon in icons
            if not (
                isinstance(icon, dict)
                and isinstance(icon.get("src"), str)
                and not is_valid_http_url(icon["src"])
            )
        ]

    remotes = sanitized.get("remotes")
    if isinstance(remotes, list):
        sanitized["remotes"] = [
            remote
            for remote in remotes
            if not (
                isinstance(remote, dict)
                and isinstance(remote.get("url"), str)
                and not is_valid_http_url(remote["url"])
            )
        ]

    packages = sanitized.get("packages")
    if isinstance(packages, list):
        sanitized_packages = []
        for package in packages:
            if not isinstance(package, dict):
                sanitized_packages.append(package)
                continue
            sanitized_package = dict(package)
            transport = sanitized_package.get("transport")
            if isinstance(transport, dict):
                sanitized_transport = dict(transport)
                url = sanitized_transport.get("url")
                if isinstance(url, str) and not is_valid_http_url(url):
                    sanitized_transport.pop("url", None)
                sanitized_package["transport"] = sanitized_transport
            sanitized_packages.append(sanitized_package)
        sanitized["packages"] = sanitized_packages

    sanitized["_meta"] = sanitize_publisher_links(sanitized.get("_meta"))
    return sanitized


def github_repo_from_url(url: str) -> tuple[str, str] | None:
    if not is_valid_http_url(url):
        return None
    split_url = urlsplit(url.strip())
    if split_url.netloc.casefold() not in {"github.com", "www.github.com"}:
        return None

    parts = [part for part in split_url.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None

    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def github_repo_from_server(server: dict) -> tuple[str, str] | None:
    repository = server.get("repository")
    if isinstance(repository, dict):
        url = repository.get("url")
        if isinstance(url, str):
            repo = github_repo_from_url(url)
            if repo:
                return repo

    website_url = server.get("websiteUrl")
    if isinstance(website_url, str):
        return github_repo_from_url(website_url)
    return None


def fetch_github_readme(
    owner: str,
    repo: str,
    *,
    github_token: str | None = None,
    timeout: int = 20,
) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    headers = {
        "Accept": "application/vnd.github.raw",
        "User-Agent": "wardn-mcp-registry-sync",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace").strip()


def enrich_server_description_from_readme(
    server: dict,
    *,
    readme_cache: dict[tuple[str, str], str | None],
    github_token: str | None = None,
) -> dict:
    repo = github_repo_from_server(server)
    if not repo:
        return server

    if repo not in readme_cache:
        try:
            readme_cache[repo] = fetch_github_readme(
                repo[0],
                repo[1],
                github_token=github_token,
            )
        except HTTPError as exc:
            if exc.code != 404:
                logger.debug("Could not fetch README for %s/%s: %s", repo[0], repo[1], exc)
            readme_cache[repo] = None
        except URLError as exc:
            logger.debug("Could not fetch README for %s/%s: %s", repo[0], repo[1], exc)
            readme_cache[repo] = None

    readme = readme_cache[repo]
    if not readme:
        return server

    enriched = dict(server)
    enriched["description"] = readme
    return enriched


def enrich_descriptions_from_readmes(
    servers: list[MCPServerCreate],
    *,
    readme_cache: dict[tuple[str, str], str | None] | None = None,
    github_token: str | None = None,
) -> list[MCPServerCreate]:
    readme_cache = readme_cache if readme_cache is not None else {}
    enriched_servers = []
    for server in servers:
        document = server.model_dump(by_alias=True, exclude_none=True)
        enriched_document = enrich_server_description_from_readme(
            document,
            readme_cache=readme_cache,
            github_token=github_token,
        )
        enriched_servers.append(MCPServerCreate.model_validate(enriched_document))
    return enriched_servers


def load_supported_servers_from_payload(
    payload,
    *,
    strip_unsupported_packages: bool = False,
    sanitize_urls: bool = False,
) -> list[MCPServerCreate]:
    documents = _server_documents_from_payload(payload)
    if strip_unsupported_packages:
        documents = [strip_unsupported_package_targets(server) for server in documents]
    if sanitize_urls:
        documents = [sanitize_source_urls(server) for server in documents]
    return [MCPServerCreate.model_validate(server) for server in documents]


def load_supported_servers(path: Path) -> list[MCPServerCreate]:
    logger.info("Loading supported MCP servers from file: %s", path)
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    servers = load_supported_servers_from_payload(payload)
    logger.info("Loaded %s supported MCP server entries from file.", len(servers))
    return servers


def url_with_query_params(
    url: str,
    *,
    cursor: str | None = None,
    page: int | None = None,
    limit: int | None = None,
    updated_since: str | None = None,
    version: str | None = None,
) -> str:
    split_url = urlsplit(url)
    query = dict(parse_qsl(split_url.query, keep_blank_values=True))
    if limit is not None and "limit" not in query:
        query["limit"] = str(limit)
    if updated_since and "updated_since" not in query:
        query["updated_since"] = updated_since
    if version and "version" not in query:
        query["version"] = version
    if cursor:
        query["cursor"] = cursor
    elif "cursor" in query:
        del query["cursor"]
    if page is not None:
        query["page"] = str(page)
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urlencode(query),
            split_url.fragment,
        )
    )


def fetch_registry_payload(url: str, headers: dict[str, str] | None = None):
    request_headers = {
        "Accept": "application/json",
        "User-Agent": REGISTRY_SYNC_USER_AGENT,
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def registry_headers(source: str, *, api_key: str | None, tenant_id: str | None) -> dict[str, str]:
    if source != "pulsemcp":
        return {}
    api_key = api_key or os.getenv("WARDN_PULSEMCP_API_KEY")
    tenant_id = tenant_id or os.getenv("WARDN_PULSEMCP_TENANT_ID")
    if not api_key:
        raise ValueError("--api-key is required for PulseMCP sync")
    if not tenant_id:
        raise ValueError("--tenant-id is required for PulseMCP sync")
    return {
        "X-API-Key": api_key,
        "X-Tenant-ID": tenant_id,
    }


def registry_source_url(source: str, source_url: str) -> str:
    if source == "pulsemcp" and source_url == DEFAULT_REGISTRY_URL:
        return PULSE_REGISTRY_URL
    return source_url


def load_supported_servers_from_registry_url(
    source_url: str,
    *,
    limit: int,
    max_pages: int | None,
    headers: dict[str, str] | None = None,
    updated_since: str | None = None,
    version: str | None = None,
    pagination: str = "cursor",
    readme_descriptions: bool = False,
    github_token: str | None = None,
) -> list[MCPServerCreate]:
    if limit < 1:
        raise ValueError("--limit must be greater than 0")
    if max_pages is not None and max_pages < 1:
        raise ValueError("--max-pages must be greater than 0")

    servers = []
    seen_server_versions: set[tuple[str, str]] = set()
    readme_cache: dict[tuple[str, str], str | None] = {}
    cursor = None
    page = 1
    pages_fetched = 0

    logger.info("Loading supported MCP servers from registry: %s", source_url)

    while True:
        previous_cursor = cursor
        page_url = url_with_query_params(
            source_url,
            cursor=cursor if pagination == "cursor" else None,
            page=page if pagination == "page" else None,
            limit=limit if pagination == "cursor" else None,
            updated_since=updated_since if pagination == "cursor" else None,
            version=version if pagination == "cursor" else None,
        )
        logger.debug("Fetching registry page %s, cursor=%s", pages_fetched + 1, cursor)
        if headers:
            payload = fetch_registry_payload(page_url, headers=headers)
        else:
            payload = fetch_registry_payload(page_url)
        page_servers = load_supported_servers_from_payload(
            payload,
            strip_unsupported_packages=True,
            sanitize_urls=True,
        )
        if readme_descriptions:
            page_servers = enrich_descriptions_from_readmes(
                page_servers,
                readme_cache=readme_cache,
                github_token=github_token,
            )
        unique_page_servers = []
        for server in page_servers:
            key = (server.name, server.version)
            if key in seen_server_versions:
                continue
            seen_server_versions.add(key)
            unique_page_servers.append(server)
        servers.extend(unique_page_servers)
        pages_fetched += 1
        repeated_count = len(page_servers) - len(unique_page_servers)

        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        cursor = metadata.get("nextCursor") if pagination == "cursor" else None
        logger.debug(
            "Fetched registry page %s: %s entries, %s unique in fetch, %s repeated in fetch.",
            pages_fetched,
            len(page_servers),
            len(unique_page_servers),
            repeated_count,
        )
        if pages_fetched % PROGRESS_PAGE_INTERVAL == 0:
            logger.info(
                "Fetched %s registry pages (%s server versions).",
                pages_fetched,
                len(servers),
            )

        if max_pages is not None and pages_fetched >= max_pages:
            logger.info("Stopped after %s registry pages.", pages_fetched)
            break
        if pagination == "page":
            total_pages = metadata.get("pages")
            if isinstance(total_pages, int) and page >= total_pages:
                logger.info("Finished paged registry fetch after %s pages.", pages_fetched)
                break
            if not page_servers:
                logger.info("Finished paged registry fetch after empty page %s.", page)
                break
            page += 1
            continue
        if not cursor:
            logger.info("Finished registry fetch after %s pages.", pages_fetched)
            break
        if cursor == previous_cursor:
            logger.warning("Stopped registry fetch because cursor did not advance: %s", cursor)
            break
        if page_servers and not unique_page_servers:
            logger.warning("Stopped registry fetch because page only repeated earlier entries.")
            break

    return servers


async def sync_mcp_registry_from_args(args: argparse.Namespace) -> int:
    if args.file:
        source = str(args.file)
        logger.info("Starting MCP registry sync from file.")
        servers = load_supported_servers(Path(args.file))
    else:
        source_type = getattr(args, "source", "official")
        source_url = registry_source_url(source_type, args.source_url)
        source = source_url
        headers = registry_headers(
            source_type,
            api_key=getattr(args, "api_key", None),
            tenant_id=getattr(args, "tenant_id", None),
        )
        version = "latest" if getattr(args, "latest_only", False) else None
        logger.info(
            "Starting MCP registry sync from %s registry, page size %s.",
            source_type,
            args.limit,
        )
        servers = load_supported_servers_from_registry_url(
            source_url,
            limit=args.limit,
            max_pages=args.max_pages,
            headers=headers,
            updated_since=getattr(args, "updated_since", None),
            version=version,
            readme_descriptions=getattr(args, "readme_descriptions", False),
            github_token=(
                getattr(args, "github_token", None)
                or os.getenv("WARDN_GITHUB_TOKEN")
                or os.getenv("GITHUB_TOKEN")
            ),
        )

    if args.dry_run:
        logger.info("Dry run complete: %s server versions validated.", len(servers))
        print(f"Loaded {len(servers)} supported MCP server entries from {source}.")
        return 0

    logger.info("Writing %s server versions to database.", len(servers))
    organization_id = (
        UUID(args.organization_id)
        if getattr(args, "organization_id", None)
        else None
    )
    async with AsyncSessionLocal() as session:
        count = await sync_supported_servers(session, servers, organization_id=organization_id)
        await session.commit()
    logger.info("MCP registry sync complete: %s server versions synced.", count)
    print(f"Synced {count} supported MCP server entries from {source}.")
    return 0


def handle_syncmcpregistry(args: argparse.Namespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(sync_mcp_registry_from_args(args))
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        URLError,
    ) as exc:
        logger.error("MCP registry sync failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        logger.error("MCP registry database sync failed: %s", exc)
        if "relation \"mcp_server_versions\" does not exist" in str(exc):
            print("Error: database is not migrated. Run `alembic upgrade head`.", file=sys.stderr)
        else:
            print(f"Database error: {exc}", file=sys.stderr)
        return 1


async def refresh_mcp_tools_from_args(args: argparse.Namespace) -> int:
    server_name = str(args.server or "").strip()
    if not server_name:
        raise ValueError("--server is required")

    logger.info("Refreshing MCP tool schemas for %s.", server_name)
    async with AsyncSessionLocal() as session:
        result = await refresh_tool_schemas(session, server_name)
        await session.commit()

    logger.info(
        "MCP tool schema refresh complete for %s: %s tools.",
        result.server_name,
        result.tool_count,
    )
    print(
        f"Refreshed {result.tool_count} tools for "
        f"{result.server_name}@{result.server_version}."
    )
    return 0


def handle_refreshmcptools(args: argparse.Namespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(refresh_mcp_tools_from_args(args))
    except (LookupError, MCPGatewayUpstreamError, ValueError) as exc:
        logger.error("MCP tool refresh failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        logger.error("MCP tool refresh database operation failed: %s", exc)
        if "relation \"mcp_server_tool_schemas\" does not exist" in str(exc):
            print("Error: database is not migrated. Run `alembic upgrade head`.", file=sys.stderr)
        else:
            print(f"Database error: {exc}", file=sys.stderr)
        return 1


async def add_mcp_server_from_args(args: argparse.Namespace) -> int:
    payload = MCPServerCreate.model_validate(CURATED_SERVERS[args.server])
    logger.info("Adding curated MCP server %s.", payload.name)
    async with AsyncSessionLocal() as session:
        count = await sync_supported_servers(session, [payload])
        await session.commit()

    print(f"Added {count} curated MCP server entry: {payload.name}@{payload.version}.")
    return 0


def handle_addmcpserver(args: argparse.Namespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(add_mcp_server_from_args(args))
    except (ValidationError, ValueError) as exc:
        logger.error("Curated MCP server add failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        logger.error("Curated MCP server database operation failed: %s", exc)
        if "relation \"mcp_server_versions\" does not exist" in str(exc):
            print("Error: database is not migrated. Run `alembic upgrade head`.", file=sys.stderr)
        else:
            print(f"Database error: {exc}", file=sys.stderr)
        return 1


def register_mcp_registry_commands(registry: CommandRegistry) -> None:
    registry.register(
        "syncmcpregistry",
        "Sync supported MCP servers from the official registry.",
        configure_syncmcpregistry_parser,
        handle_syncmcpregistry,
    )
    registry.register(
        "refreshmcptools",
        "Refresh cached MCP tool schemas for one enabled server.",
        configure_refreshmcptools_parser,
        handle_refreshmcptools,
    )
    registry.register(
        "addmcpserver",
        "Add one curated supported MCP server to the catalog.",
        configure_addmcpserver_parser,
        handle_addmcpserver,
    )
