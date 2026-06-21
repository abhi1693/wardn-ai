import argparse
import asyncio
import logging
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandRegistry
from app.db.session import AsyncSessionLocal
from app.modules.mcp_runtime.service import reap_expired_runtime_sessions

logger = logging.getLogger(__name__)


def configure_reapmcpruntimes_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of expired runtime sessions to stop.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed runtime reaper logs.",
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


async def reap_mcp_runtimes_from_args(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise ValueError("--limit must be greater than 0")

    logger.info("Reaping expired MCP runtime sessions, limit %s.", args.limit)
    async with AsyncSessionLocal() as session:
        result = await reap_expired_runtime_sessions(session, limit=args.limit)
        await session.commit()

    logger.info("MCP runtime reaper stopped %s sessions.", result.stopped_count)
    print(f"Stopped {result.stopped_count} expired MCP runtime sessions.")
    return 0


def handle_reapmcpruntimes(args: argparse.Namespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(reap_mcp_runtimes_from_args(args))
    except ValueError as exc:
        logger.error("MCP runtime reaper failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        logger.error("MCP runtime reaper database operation failed: %s", exc)
        if "relation \"mcp_runtime_sessions\" does not exist" in str(exc):
            print("Error: database is not migrated. Run `alembic upgrade head`.", file=sys.stderr)
        else:
            print(f"Database error: {exc}", file=sys.stderr)
        return 1


def register_mcp_runtime_commands(registry: CommandRegistry) -> None:
    registry.register(
        "reapmcpruntimes",
        "Stop expired MCP runtime sessions.",
        configure_reapmcpruntimes_parser,
        handle_reapmcpruntimes,
    )
