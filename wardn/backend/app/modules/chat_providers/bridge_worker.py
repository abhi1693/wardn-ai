import asyncio
import json
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

from app.db.session import AsyncSessionLocal
from app.modules.chat_providers import repository, service
from app.modules.chat_providers.models import ChatProviderConnection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsAppBridgeSubscription:
    connection_id: uuid.UUID
    base_url: str
    user_id: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.base_url, self.user_id)


@dataclass(frozen=True)
class SlackSocketModeSubscription:
    connection_id: uuid.UUID
    team_id: str
    app_id: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.team_id, self.app_id)


def retry_delay_seconds(
    attempt: int,
    *,
    base_seconds: float,
    max_seconds: float,
) -> float:
    return min(base_seconds * (2 ** max(attempt - 1, 0)), max_seconds)


async def iter_sse_events(response: httpx.Response):
    event_type = "message"
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield event_type, "\n".join(data_lines)
            event_type = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value or "message"
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        yield event_type, "\n".join(data_lines)


async def iter_sse_events_until_idle_timeout(
    response: httpx.Response,
    *,
    stream_seconds: float,
):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + stream_seconds
    events = iter_sse_events(response).__aiter__()
    while True:
        remaining_seconds = deadline - loop.time()
        if remaining_seconds <= 0:
            raise TimeoutError
        try:
            yield await asyncio.wait_for(events.__anext__(), timeout=remaining_seconds)
        except StopAsyncIteration:
            return


def decode_bridge_event_data(data: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def bridge_subscription(connection: ChatProviderConnection) -> WhatsAppBridgeSubscription | None:
    target = service.whatsapp_bridge_target(connection)
    if target is None:
        return None
    if not target.user_id.isdigit():
        logger.warning(
            "Skipping WhatsApp bridge stream because bridge user id is not numeric.",
            extra={
                "chat_provider_connection_id": str(connection.id),
                "chat_provider_bridge_user_id": target.user_id,
            },
        )
        return None
    return WhatsAppBridgeSubscription(
        connection_id=connection.id,
        base_url=target.base_url,
        user_id=target.user_id,
    )


def slack_socket_mode_subscription(
    connection: ChatProviderConnection,
) -> SlackSocketModeSubscription | None:
    team_id = service.configured_slack_team_id(connection)
    app_id = ""
    try:
        app_id = service.SlackProviderConfig.model_validate(connection.config or {}).app_id
    except Exception:
        app_id = ""
    if not team_id:
        logger.warning(
            "Skipping Slack Socket Mode stream because Slack team id is not configured.",
            extra={"chat_provider_connection_id": str(connection.id)},
        )
        return None
    return SlackSocketModeSubscription(
        connection_id=connection.id,
        team_id=team_id,
        app_id=app_id,
    )


class WhatsAppBridgeEventWorker:
    def __init__(
        self,
        *,
        stream_seconds: float,
        retry_base_seconds: float,
        retry_max_seconds: float,
    ) -> None:
        self.stream_seconds = stream_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self._subscriptions: dict[uuid.UUID, WhatsAppBridgeSubscription] = {}
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    async def reconcile(self, connections: list[ChatProviderConnection]) -> None:
        desired = {
            subscription.connection_id: subscription
            for connection in connections
            if (subscription := bridge_subscription(connection)) is not None
        }
        for connection_id, task in list(self._tasks.items()):
            current = self._subscriptions.get(connection_id)
            if connection_id not in desired or desired[connection_id].key != current.key:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                self._tasks.pop(connection_id, None)
                self._subscriptions.pop(connection_id, None)

        for connection_id, subscription in desired.items():
            task = self._tasks.get(connection_id)
            if task is not None and not task.done():
                continue
            self._subscriptions[connection_id] = subscription
            self._tasks[connection_id] = asyncio.create_task(
                self._run_subscription(subscription),
                name=f"whatsapp-bridge-events:{connection_id}",
            )

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        self._subscriptions.clear()

    async def _run_subscription(self, subscription: WhatsAppBridgeSubscription) -> None:
        attempt = 0
        while True:
            try:
                await self._stream_once(subscription)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                attempt = 0
            except Exception as exc:
                attempt += 1
                delay = retry_delay_seconds(
                    attempt,
                    base_seconds=self.retry_base_seconds,
                    max_seconds=self.retry_max_seconds,
                )
                logger.warning(
                    "WhatsApp bridge event stream failed; reconnecting.",
                    extra={
                        "chat_provider_connection_id": str(subscription.connection_id),
                        "chat_provider_bridge_base_url": subscription.base_url,
                        "chat_provider_bridge_user_id": subscription.user_id,
                        "retry_delay_seconds": delay,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(delay)

    async def _stream_once(self, subscription: WhatsAppBridgeSubscription) -> None:
        target = service.WhatsAppBridgeTarget(
            base_url=subscription.base_url,
            user_id=subscription.user_id,
        )
        timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            create_response = await client.post(
                service.whatsapp_bridge_url(target, "/sessions"),
                json={"user_id": service.whatsapp_bridge_user_value(subscription.user_id)},
            )
            if create_response.status_code >= 500:
                raise RuntimeError(
                    f"WhatsApp bridge session create failed with HTTP "
                    f"{create_response.status_code}"
                )
            async with client.stream(
                "GET",
                service.whatsapp_bridge_url(target, "/events"),
                params={"user_id": service.whatsapp_bridge_user_value(subscription.user_id)},
            ) as response:
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"WhatsApp bridge event stream failed with HTTP {response.status_code}"
                    )
                async for event_type, data in iter_sse_events_until_idle_timeout(
                    response,
                    stream_seconds=self.stream_seconds,
                ):
                    if event_type != "message":
                        continue
                    payload = decode_bridge_event_data(data)
                    if payload is None:
                        continue
                    await process_bridge_event(subscription.connection_id, payload)


async def process_bridge_event(
    connection_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            connection = await repository.get_active_connection_by_id(
                session,
                connection_id=connection_id,
            )
            if connection is None or connection.provider != service.PROVIDER_WHATSAPP_LOCAL:
                return
            await service.handle_whatsapp_local_bridge_event(session, connection, payload)
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def open_slack_socket_url(connection_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as session:
        connection = await repository.get_active_connection_by_id(
            session,
            connection_id=connection_id,
        )
        if connection is None or connection.provider != service.PROVIDER_SLACK:
            return ""
        app_token = await service.slack_app_token(session, connection)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://slack.com/api/apps.connections.open",
            headers={"Authorization": f"Bearer {app_token}"},
        )
    payload = service.response_json(response)
    if response.status_code >= 400 or payload.get("ok") is False:
        error = str(payload.get("error") or f"HTTP {response.status_code}")
        raise RuntimeError(f"Slack Socket Mode connection open failed: {error}")
    url = str(payload.get("url") or "").strip()
    if not url:
        raise RuntimeError("Slack Socket Mode connection open returned no websocket URL")
    return url


def decode_slack_socket_message(data: str | bytes) -> dict[str, Any] | None:
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


class SlackSocketModeEventWorker:
    def __init__(
        self,
        *,
        retry_base_seconds: float,
        retry_max_seconds: float,
    ) -> None:
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self._subscriptions: dict[uuid.UUID, SlackSocketModeSubscription] = {}
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    async def reconcile(self, connections: list[ChatProviderConnection]) -> None:
        desired = {
            subscription.connection_id: subscription
            for connection in connections
            if (subscription := slack_socket_mode_subscription(connection)) is not None
        }
        for connection_id, task in list(self._tasks.items()):
            current = self._subscriptions.get(connection_id)
            if connection_id not in desired or desired[connection_id].key != current.key:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                self._tasks.pop(connection_id, None)
                self._subscriptions.pop(connection_id, None)

        for connection_id, subscription in desired.items():
            task = self._tasks.get(connection_id)
            if task is not None and not task.done():
                continue
            self._subscriptions[connection_id] = subscription
            self._tasks[connection_id] = asyncio.create_task(
                self._run_subscription(subscription),
                name=f"slack-socket-mode:{connection_id}",
            )

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        self._subscriptions.clear()

    async def _run_subscription(self, subscription: SlackSocketModeSubscription) -> None:
        attempt = 0
        while True:
            try:
                await self._stream_once(subscription)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = retry_delay_seconds(
                    attempt,
                    base_seconds=self.retry_base_seconds,
                    max_seconds=self.retry_max_seconds,
                )
                logger.warning(
                    "Slack Socket Mode stream failed; reconnecting.",
                    extra={
                        "chat_provider_connection_id": str(subscription.connection_id),
                        "chat_provider_slack_team_id": subscription.team_id,
                        "chat_provider_slack_app_id": subscription.app_id,
                        "retry_delay_seconds": delay,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(delay)

    async def _stream_once(self, subscription: SlackSocketModeSubscription) -> None:
        socket_url = await open_slack_socket_url(subscription.connection_id)
        if not socket_url:
            return
        async with websockets.connect(socket_url, open_timeout=10, ping_interval=20) as websocket:
            async for raw_message in websocket:
                message = decode_slack_socket_message(raw_message)
                if message is None:
                    continue
                envelope_id = str(message.get("envelope_id") or "").strip()
                if envelope_id:
                    await websocket.send(json.dumps({"envelope_id": envelope_id}))
                message_type = str(message.get("type") or "").strip()
                if message_type == "events_api":
                    payload = message.get("payload")
                    if isinstance(payload, dict):
                        await process_slack_socket_mode_event(subscription.connection_id, payload)
                    continue
                if message_type == "disconnect":
                    return


async def process_slack_socket_mode_event(
    connection_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            connection = await repository.get_active_connection_by_id(
                session,
                connection_id=connection_id,
            )
            if connection is None or connection.provider != service.PROVIDER_SLACK:
                return
            await service.handle_slack_socket_mode_event(
                session,
                connection_id=connection_id,
                payload=payload,
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def run_chat_provider_event_worker_loop(
    *,
    poll_interval_seconds: float,
    stream_seconds: float,
    retry_base_seconds: float,
    retry_max_seconds: float,
    sleep=asyncio.sleep,
) -> None:
    whatsapp_worker = WhatsAppBridgeEventWorker(
        stream_seconds=stream_seconds,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    slack_worker = SlackSocketModeEventWorker(
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    try:
        while True:
            async with AsyncSessionLocal() as session:
                whatsapp_connections = await repository.list_active_whatsapp_connections(session)
                slack_connections = await repository.list_active_slack_connections(session)
            await whatsapp_worker.reconcile(whatsapp_connections)
            await slack_worker.reconcile(slack_connections)
            await sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        raise
    finally:
        await whatsapp_worker.stop()
        await slack_worker.stop()
