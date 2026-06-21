import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandRegistry
from app.db.session import AsyncSessionLocal
from app.modules.mcp_registry.schemas import MCPServerCreate
from app.modules.mcp_registry.service import sync_supported_servers

DEFAULT_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
DEFAULT_REGISTRY_LIMIT = 100
PROGRESS_PAGE_INTERVAL = 10
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
        else:
            documents.append(item)

    return documents


def load_supported_servers_from_payload(payload) -> list[MCPServerCreate]:
    documents = _server_documents_from_payload(payload)
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
    limit: int | None = None,
) -> str:
    split_url = urlsplit(url)
    query = dict(parse_qsl(split_url.query, keep_blank_values=True))
    if limit is not None and "limit" not in query:
        query["limit"] = str(limit)
    if cursor:
        query["cursor"] = cursor
    elif "cursor" in query:
        del query["cursor"]
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urlencode(query),
            split_url.fragment,
        )
    )


def fetch_registry_payload(url: str):
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_supported_servers_from_registry_url(
    source_url: str,
    *,
    limit: int,
    max_pages: int | None,
) -> list[MCPServerCreate]:
    if limit < 1:
        raise ValueError("--limit must be greater than 0")
    if max_pages is not None and max_pages < 1:
        raise ValueError("--max-pages must be greater than 0")

    servers = []
    seen_server_versions: set[tuple[str, str]] = set()
    cursor = None
    pages_fetched = 0

    logger.info("Loading supported MCP servers from registry: %s", source_url)

    while True:
        previous_cursor = cursor
        page_url = url_with_query_params(source_url, cursor=cursor, limit=limit)
        logger.debug("Fetching registry page %s, cursor=%s", pages_fetched + 1, cursor)
        payload = fetch_registry_payload(page_url)
        page_servers = load_supported_servers_from_payload(payload)
        new_servers = []
        for server in page_servers:
            key = (server.name, server.version)
            if key in seen_server_versions:
                continue
            seen_server_versions.add(key)
            new_servers.append(server)
        servers.extend(new_servers)
        pages_fetched += 1
        duplicate_count = len(page_servers) - len(new_servers)

        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        cursor = metadata.get("nextCursor")
        logger.debug(
            "Fetched registry page %s: %s entries, %s new, %s duplicates.",
            pages_fetched,
            len(page_servers),
            len(new_servers),
            duplicate_count,
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
        if not cursor:
            logger.info("Finished registry fetch after %s pages.", pages_fetched)
            break
        if cursor == previous_cursor:
            logger.warning("Stopped registry fetch because cursor did not advance: %s", cursor)
            break
        if page_servers and not new_servers:
            logger.warning("Stopped registry fetch because page only contained duplicates.")
            break

    return servers


async def sync_mcp_registry_from_args(args: argparse.Namespace) -> int:
    if args.file:
        source = str(args.file)
        logger.info("Starting MCP registry sync from file.")
        servers = load_supported_servers(Path(args.file))
    else:
        source = args.source_url
        logger.info(
            "Starting MCP registry sync from official registry, page size %s.",
            args.limit,
        )
        servers = load_supported_servers_from_registry_url(
            args.source_url,
            limit=args.limit,
            max_pages=args.max_pages,
        )

    if args.dry_run:
        logger.info("Dry run complete: %s server versions validated.", len(servers))
        print(f"Loaded {len(servers)} supported MCP server entries from {source}.")
        return 0

    logger.info("Writing %s server versions to database.", len(servers))
    async with AsyncSessionLocal() as session:
        count = await sync_supported_servers(session, servers)
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


def register_mcp_registry_commands(registry: CommandRegistry) -> None:
    registry.register(
        "syncmcpregistry",
        "Sync supported MCP servers from the official registry.",
        configure_syncmcpregistry_parser,
        handle_syncmcpregistry,
    )
