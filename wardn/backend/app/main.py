from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.mcp_runtime.reaper import start_runtime_reaper, stop_runtime_reaper


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    reaper_task = start_runtime_reaper(
        interval_seconds=settings.mcp_runtime_reaper_interval_seconds,
        limit=settings.mcp_runtime_reaper_batch_size,
        event_retention_days=settings.mcp_runtime_event_retention_days,
        invocation_retention_days=settings.mcp_runtime_invocation_retention_days,
    )
    app.state.mcp_runtime_reaper_task = reaper_task
    try:
        yield
    finally:
        await stop_runtime_reaper(reaper_task)


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

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
