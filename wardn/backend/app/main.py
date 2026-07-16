from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.http_errors import configure_error_handling
from app.api.request_id import RequestIDMiddleware
from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import engine
from app.modules.mcp_gateway.oauth import well_known_router as mcp_gateway_oauth_well_known_router
from app.modules.mcp_runtime.reaper import start_runtime_reaper, stop_runtime_reaper
from app.modules.mcp_runtime.shutdown import teardown_runtime_sessions
from app.modules.mcp_runtime.warmup import start_runtime_warmup, stop_runtime_warmup


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(engine.dispose)
        cleanup.push_async_callback(
            teardown_runtime_sessions,
            limit=settings.mcp_runtime_reaper_batch_size,
        )
        reaper_task = start_runtime_reaper(
            interval_seconds=settings.mcp_runtime_reaper_interval_seconds,
            limit=settings.mcp_runtime_reaper_batch_size,
            event_retention_days=settings.mcp_runtime_event_retention_days,
            invocation_retention_days=settings.mcp_runtime_invocation_retention_days,
        )
        cleanup.push_async_callback(stop_runtime_reaper, reaper_task)
        warmup_task = start_runtime_warmup(
            concurrency=settings.mcp_runtime_warm_startup_concurrency,
        )
        cleanup.push_async_callback(stop_runtime_warmup, warmup_task)
        app.state.mcp_runtime_reaper_task = reaper_task
        app.state.mcp_runtime_warmup_task = warmup_task
        yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    configure_error_handling(app)

    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(mcp_gateway_oauth_well_known_router)
    return app


app = create_app()
