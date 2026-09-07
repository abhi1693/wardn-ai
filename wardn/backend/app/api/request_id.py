import asyncio
import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.http_errors import REQUEST_ID_HEADER, SAFE_REQUEST_ID_PATTERN
from app.core.http_logging import request_log_fields
from app.core.logging import elapsed_ms, log_context

logger = logging.getLogger(__name__)


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        supplied_request_id = headers.get(REQUEST_ID_HEADER.lower().encode())
        candidate = (
            supplied_request_id.decode("ascii", errors="ignore") if supplied_request_id else ""
        )
        request_id = candidate if SAFE_REQUEST_ID_PATTERN.fullmatch(candidate) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        started = time.perf_counter()
        status = 500
        failed = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = list(message.get("headers", []))
                header_name = REQUEST_ID_HEADER.lower().encode()
                if not any(name == header_name for name, _ in response_headers):
                    response_headers.append((header_name, request_id.encode()))
                    message["headers"] = response_headers
            await send(message)

        with log_context(service="api", request_id=request_id, **request_log_fields(scope)):
            try:
                await self.app(scope, receive, send_with_request_id)
            except asyncio.CancelledError:
                status = 499
                raise
            except Exception:
                failed = True
                scope["state"]["request_failure_logged"] = True
                logger.exception("request_failed")
                raise
            finally:
                level = (
                    logging.ERROR
                    if failed or status >= 500
                    else logging.WARNING
                    if status >= 400
                    else logging.INFO
                )
                if (
                    status < 400
                    and not failed
                    and scope["path"].rstrip("/").endswith(("/health/live", "/health/ready"))
                ):
                    level = logging.DEBUG
                logger.log(
                    level,
                    "request_completed",
                    extra={"status_code": status, "duration_ms": elapsed_ms(started)},
                )
