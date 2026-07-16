import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.http_errors import REQUEST_ID_HEADER, SAFE_REQUEST_ID_PATTERN


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
        request_id = (
            candidate if SAFE_REQUEST_ID_PATTERN.fullmatch(candidate) else uuid.uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                header_name = REQUEST_ID_HEADER.lower().encode()
                if not any(name == header_name for name, _ in response_headers):
                    response_headers.append((header_name, request_id.encode()))
                    message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)
