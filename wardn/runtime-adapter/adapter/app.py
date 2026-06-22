import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status

from adapter.config import AdapterSettings, settings_from_env
from adapter.constants import (
    ADAPTER_HEALTH_PATH,
    ADAPTER_MCP_PATH,
    ADAPTER_READY_PATH,
    ADAPTER_SHUTDOWN_PATH,
)
from adapter.stdio_bridge import AdapterError, MCPStdioBridge, RuntimeNotReadyError

logger = logging.getLogger(__name__)


def create_app(settings: AdapterSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bridge = MCPStdioBridge(settings or settings_from_env())
        app.state.bridge = bridge
        try:
            await bridge.start()
        except Exception as exc:
            logger.exception("Runtime adapter failed to initialize stdio process.")
            bridge.start_error = str(exc)
        try:
            yield
        finally:
            await bridge.stop()

    app = FastAPI(
        title="Wardn Runtime Adapter",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get(ADAPTER_HEALTH_PATH)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(ADAPTER_READY_PATH)
    async def readyz() -> dict[str, Any]:
        bridge: MCPStdioBridge = app.state.bridge
        details = bridge.status()
        if not details["ready"]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=details,
            )
        return details

    @app.post(ADAPTER_MCP_PATH, response_model=None)
    async def mcp(payload: dict[str, Any]) -> dict[str, Any] | Response:
        bridge: MCPStdioBridge = app.state.bridge
        if not bridge.status()["ready"]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=bridge.status(),
            )
        if "jsonrpc" not in payload or "method" not in payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="request must be a JSON-RPC object",
            )
        try:
            if "id" not in payload:
                await bridge.notify(payload)
                return Response(status_code=status.HTTP_202_ACCEPTED)
            return await bridge.request(payload)
        except RuntimeNotReadyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except AdapterError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    @app.post(ADAPTER_SHUTDOWN_PATH)
    async def shutdown() -> dict[str, str]:
        bridge: MCPStdioBridge = app.state.bridge
        await bridge.stop()
        return {"status": "stopped"}

    return app
