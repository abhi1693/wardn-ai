import asyncio
import logging
import sys
from contextlib import suppress
from types import SimpleNamespace
from typing import Annotated

import typer
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.exc import SQLAlchemyError

from app.cli_utils import exit_with_code
from app.core.config import Settings, get_settings
from app.modules.chat_providers.bridge_worker import run_whatsapp_bridge_event_worker_loop
from app.modules.mcp_registry.job_handlers import build_job_handlers
from app.modules.mcp_registry.job_worker import (
    default_worker_id,
    run_job_worker_loop,
    run_job_worker_once,
)
from app.modules.mcp_runtime.reaper import start_runtime_reaper, stop_runtime_reaper
from app.modules.mcp_runtime.warmup import start_runtime_warmup, stop_runtime_warmup
from app.modules.secrets.cleanup_worker import (
    run_cleanup_worker_loop,
    run_cleanup_worker_once,
)

logger = logging.getLogger(__name__)


def configure_command_logging(*, verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
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


async def run_mcp_jobs_from_args(args: SimpleNamespace) -> int:
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
        worked = await run_job_worker_once(**kwargs)
        if not worked:
            await run_cleanup_worker_once(
                worker_id=f"{worker_id}:secrets",
                lease_seconds=settings.secret_cleanup_worker_lease_seconds,
                provisioning_grace_seconds=settings.secret_cleanup_provisioning_grace_seconds,
                retry_base_seconds=settings.secret_cleanup_worker_retry_base_seconds,
                retry_max_seconds=settings.secret_cleanup_worker_retry_max_seconds,
            )
        return 0
    secret_cleanup_task = asyncio.create_task(
        run_cleanup_worker_loop(
            worker_id=f"{worker_id}:secrets",
            poll_interval_seconds=settings.secret_cleanup_worker_poll_interval_seconds,
            lease_seconds=settings.secret_cleanup_worker_lease_seconds,
            provisioning_grace_seconds=settings.secret_cleanup_provisioning_grace_seconds,
            retry_base_seconds=settings.secret_cleanup_worker_retry_base_seconds,
            retry_max_seconds=settings.secret_cleanup_worker_retry_max_seconds,
        )
    )
    chat_provider_event_task: asyncio.Task[None] | None = None
    if settings.chat_provider_event_worker_enabled:
        chat_provider_event_task = asyncio.create_task(
            run_whatsapp_bridge_event_worker_loop(
                poll_interval_seconds=settings.chat_provider_event_worker_poll_interval_seconds,
                stream_seconds=settings.chat_provider_event_worker_stream_seconds,
                retry_base_seconds=settings.chat_provider_event_worker_retry_base_seconds,
                retry_max_seconds=settings.chat_provider_event_worker_retry_max_seconds,
            ),
            name="chat-provider-events",
        )
    warmup_task = start_runtime_warmup(
        concurrency=settings.mcp_runtime_warm_startup_concurrency,
    )
    reaper_task = start_runtime_reaper(
        interval_seconds=settings.mcp_runtime_reaper_interval_seconds,
        limit=settings.mcp_runtime_reaper_batch_size,
        event_retention_days=settings.mcp_runtime_event_retention_days,
        invocation_retention_days=settings.mcp_runtime_invocation_retention_days,
    )
    try:
        await run_job_worker_loop(poll_interval_seconds=poll_interval_seconds, **kwargs)
    finally:
        secret_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await secret_cleanup_task
        if chat_provider_event_task is not None:
            chat_provider_event_task.cancel()
            with suppress(asyncio.CancelledError):
                await chat_provider_event_task
        await stop_runtime_warmup(warmup_task)
        await stop_runtime_reaper(reaper_task)
    return 0


def handle_runmcpjobs(args: SimpleNamespace) -> int:
    configure_command_logging(verbose=args.verbose)
    try:
        return asyncio.run(run_mcp_jobs_from_args(args))
    except (ValueError, SQLAlchemyError) as exc:
        logger.error("MCP operation worker failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def runmcpjobs_command(
    once: Annotated[bool, typer.Option("--once", help="Process at most one job and exit.")] = False,
    worker_id: Annotated[
        str,
        typer.Option(help="Stable worker identifier for logs and leases."),
    ] = "",
    poll_interval: Annotated[
        float | None,
        typer.Option(help="Seconds to wait when no work is available."),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show detailed worker logs.")] = False,
) -> None:
    exit_with_code(
        handle_runmcpjobs(
            SimpleNamespace(
                once=once,
                worker_id=worker_id,
                poll_interval=poll_interval,
                verbose=verbose,
            )
        )
    )


def register_mcp_job_commands(app: typer.Typer) -> None:
    app.command(
        "runmcpjobs",
        help="Run durable MCP installation and synchronization jobs.",
    )(runmcpjobs_command)
