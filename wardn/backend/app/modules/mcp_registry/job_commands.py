import argparse
import asyncio
import logging
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandRegistry
from app.core.config import Settings, get_settings
from app.modules.mcp_registry.job_handlers import build_job_handlers
from app.modules.mcp_registry.job_worker import (
    default_worker_id,
    run_job_worker_loop,
    run_job_worker_once,
)

logger = logging.getLogger(__name__)


def configure_runmcpjobs_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    parser.add_argument(
        "--worker-id",
        default="",
        help="Stable worker identifier for logs and leases.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Seconds to wait when no work is available.",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed worker logs.")


def configure_command_logging(*, verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def validate_worker_settings(settings: Settings, *, poll_interval_seconds: float) -> None:
    if poll_interval_seconds <= 0:
        raise ValueError("worker poll interval must be greater than 0")
    if settings.mcp_job_worker_lease_seconds < 2:
        raise ValueError("MCP job worker lease must be at least 2 seconds")
    if not 0 < settings.mcp_job_worker_heartbeat_seconds < settings.mcp_job_worker_lease_seconds:
        raise ValueError("MCP job worker heartbeat must be shorter than its lease")
    if settings.mcp_job_worker_retry_base_seconds < 1:
        raise ValueError("MCP job worker retry base must be at least 1 second")
    if settings.mcp_job_worker_retry_max_seconds < settings.mcp_job_worker_retry_base_seconds:
        raise ValueError("MCP job worker retry maximum must not be shorter than its base")
    if (
        settings.environment.strip().casefold() != "local"
        and settings.mcp_job_worker_isolation != "container"
    ):
        raise ValueError(
            "non-local MCP job workers must run in a dedicated isolated container or pod; "
            "set WARDN_MCP_JOB_WORKER_ISOLATION=container only in that deployment"
        )


async def run_mcp_jobs_from_args(args: argparse.Namespace) -> int:
    settings = get_settings()
    poll_interval_seconds = (
        settings.mcp_job_worker_poll_interval_seconds
        if args.poll_interval is None
        else args.poll_interval
    )
    validate_worker_settings(settings, poll_interval_seconds=poll_interval_seconds)
    worker_id = args.worker_id.strip() or default_worker_id()
    handlers = build_job_handlers()
    kwargs = {
        "worker_id": worker_id,
        "handlers": handlers,
        "lease_seconds": settings.mcp_job_worker_lease_seconds,
        "heartbeat_seconds": settings.mcp_job_worker_heartbeat_seconds,
        "retry_base_seconds": settings.mcp_job_worker_retry_base_seconds,
        "retry_max_seconds": settings.mcp_job_worker_retry_max_seconds,
    }
    logger.info("Starting isolated MCP operation worker %s.", worker_id)
    if args.once:
        await run_job_worker_once(**kwargs)
        return 0
    await run_job_worker_loop(poll_interval_seconds=poll_interval_seconds, **kwargs)
    return 0


def handle_runmcpjobs(args: argparse.Namespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(run_mcp_jobs_from_args(args))
    except (ValueError, SQLAlchemyError) as exc:
        logger.error("MCP operation worker failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def register_mcp_job_commands(registry: CommandRegistry) -> None:
    registry.register(
        "runmcpjobs",
        "Run durable MCP installation and synchronization jobs.",
        configure_runmcpjobs_parser,
        handle_runmcpjobs,
    )
