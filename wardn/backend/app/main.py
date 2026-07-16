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
from app.modules.mcp_runtime.shutdown import teardown_local_runtime_processes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(engine.dispose)
        cleanup.push_async_callback(teardown_local_runtime_processes)
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
