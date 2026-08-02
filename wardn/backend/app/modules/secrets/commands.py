import asyncio
import logging
import sys
from types import SimpleNamespace
from typing import Annotated

import typer
from sqlalchemy.exc import SQLAlchemyError

from app.cli_utils import exit_with_code
from app.core.config import Settings, get_settings
from app.modules.secrets.cleanup_worker import (
    default_worker_id,
    run_cleanup_worker_loop,
    run_cleanup_worker_once,
)

logger = logging.getLogger(__name__)


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
        raise ValueError("secret cleanup worker poll interval must be greater than 0")
    if settings.secret_cleanup_worker_lease_seconds < 10:
        raise ValueError("secret cleanup worker lease must be at least 10 seconds")
    if (
        settings.secret_cleanup_worker_retry_base_seconds
        > settings.secret_cleanup_worker_retry_max_seconds
    ):
        raise ValueError("secret cleanup worker retry base must not exceed its maximum")


async def run_secret_cleanup_from_args(args: SimpleNamespace) -> int:
    settings = get_settings()
    poll_interval_seconds = (
        settings.secret_cleanup_worker_poll_interval_seconds
        if args.poll_interval is None
        else args.poll_interval
    )
    validate_worker_settings(settings, poll_interval_seconds=poll_interval_seconds)
    kwargs = {
        "worker_id": args.worker_id.strip() or default_worker_id(),
        "lease_seconds": settings.secret_cleanup_worker_lease_seconds,
        "provisioning_grace_seconds": settings.secret_cleanup_provisioning_grace_seconds,
        "retry_base_seconds": settings.secret_cleanup_worker_retry_base_seconds,
        "retry_max_seconds": settings.secret_cleanup_worker_retry_max_seconds,
    }
    if args.once:
        await run_cleanup_worker_once(**kwargs)
        return 0
    await run_cleanup_worker_loop(
        poll_interval_seconds=poll_interval_seconds,
        **kwargs,
    )
    return 0


def handle_runsecretcleanup(args: SimpleNamespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(run_secret_cleanup_from_args(args))
    except (ValueError, SQLAlchemyError) as exc:
        logger.error("Secret cleanup worker failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def runsecretcleanup_command(
    once: Annotated[
        bool,
        typer.Option("--once", help="Process at most one cleanup and exit."),
    ] = False,
    worker_id: Annotated[str, typer.Option(help="Stable worker identifier for leases.")] = "",
    poll_interval: Annotated[
        float | None,
        typer.Option(help="Seconds to wait when no cleanup is available."),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show detailed worker logs.")] = False,
) -> None:
    exit_with_code(
        handle_runsecretcleanup(
            SimpleNamespace(
                once=once,
                worker_id=worker_id,
                poll_interval=poll_interval,
                verbose=verbose,
            )
        )
    )


def register_secret_commands(app: typer.Typer) -> None:
    app.command(
        "runsecretcleanup",
        help="Run durable cleanup for Wardn-managed external secrets.",
    )(runsecretcleanup_command)
