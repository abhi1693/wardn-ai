from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.modules.agents.models import AgentToolApproval, WorkspaceConversation
from app.modules.agents.schemas import (
    AgentConversationResponse,
    AgentRead,
    WorkspaceConversationRead,
)
from app.modules.chat_providers import service
from app.modules.chat_providers.exceptions import (
    ChatProviderDeliveryError,
    ChatProviderWebhookAuthError,
    InvalidChatProviderConnectionError,
)
from app.modules.chat_providers.models import (
    ChatProviderConnection,
    ChatProviderConnectionSecret,
    ChatProviderEvent,
    ChatProviderThread,
)
from app.modules.chat_providers.schemas import ChatProviderConnectionCreate
from app.modules.secrets.provider import ResolvedSecret
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        now = datetime(2026, 8, 2, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            instance.created_at = getattr(instance, "created_at", None) or now
            instance.updated_at = getattr(instance, "updated_at", None) or now

    async def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        now = datetime(2026, 8, 2, tzinfo=UTC)
        instance.created_at = getattr(instance, "created_at", None) or now
        instance.updated_at = getattr(instance, "updated_at", None) or now

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, *args, **kwargs):
        return SimpleNamespace()


def make_connection(provider: str = service.PROVIDER_WHATSAPP_LOCAL) -> ChatProviderConnection:
    return ChatProviderConnection(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        created_by_id=uuid4(),
        provider=provider,
        name="Personal WhatsApp" if provider == service.PROVIDER_WHATSAPP_LOCAL else "Telegram",
        external_id="personal",
        display_name="Personal WhatsApp",
        config={
            "allow_all_senders": True,
            "outbound_webhook_url": "http://bridge.local/send",
        }
        if provider == service.PROVIDER_WHATSAPP_LOCAL
        else {"allow_all_senders": True},
        is_active=True,
    )


def test_qr_payload_from_bridge_data_accepts_sse_json() -> None:
    assert (
        service.qr_payload_from_bridge_data('{"qr":"2@abcd,1234"}')
        == "2@abcd,1234"
    )
    assert service.qr_payload_from_bridge_data("2@plain") == "2@plain"


def test_bridge_status_from_payload_normalizes_connected_state() -> None:
    status, message, phone_number = service.bridge_status_from_payload(
        {"connected": True, "logged_in": True, "phone_number": "+15551234567"}
    )

    assert status == "connected"
    assert message == "WhatsApp session is connected."
    assert phone_number == "+15551234567"


def test_bridge_status_from_payload_rejects_half_linked_state() -> None:
    status, message, phone_number = service.bridge_status_from_payload(
        {"connected": True, "logged_in": False, "phone_number": "+15551234567"}
    )

    assert status == "needs_pairing"
    assert "not linked" in message
    assert phone_number == "+15551234567"


def test_normalize_whatsapp_config_replaces_loopback_with_deployment_bridge() -> None:
    settings = Settings(
        _env_file=None,
        chat_provider_whatsapp_bridge_base_url="http://wardn-ai-whatsapp-bridge:8090/",
    )

    config = service.normalize_connection_config(
        service.PROVIDER_WHATSAPP_LOCAL,
        {"bridgeBaseUrl": "http://localhost:8090", "bridgeUserId": "95273632"},
        settings=settings,
    )

    assert config["bridge_base_url"] == "http://wardn-ai-whatsapp-bridge:8090"
    assert config["bridge_user_id"] == "95273632"


def test_provider_config_defaults_allow_all_senders() -> None:
    assert service.normalize_connection_config(
        service.PROVIDER_WHATSAPP_LOCAL,
        {},
    )["allow_all_senders"] is True
    assert service.normalize_connection_config(
        service.PROVIDER_TELEGRAM,
        {},
    )["allow_all_senders"] is True


@pytest.mark.asyncio
async def test_connection_response_includes_known_provider_identities(monkeypatch) -> None:
    connection = make_connection()
    now = datetime(2026, 8, 2, tzinfo=UTC)
    connection.created_at = now
    connection.updated_at = now
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="164750684061759@lid",
        external_user_id="164750684061759@lid",
        external_user_display_name="Abhimanyu Saharan",
    )
    thread.created_at = now
    thread.updated_at = now

    async def connection_secret_handle_ids(*args, **kwargs):
        return {}

    async def list_threads_for_connection(*args, **kwargs):
        return [thread]

    monkeypatch.setattr(service, "connection_secret_handle_ids", connection_secret_handle_ids)
    monkeypatch.setattr(
        service.repository,
        "list_threads_for_connection",
        list_threads_for_connection,
    )

    response = await service.connection_response(FakeSession(), connection)

    assert len(response.known_identities) == 1
    assert response.known_identities[0].display_name == "Abhimanyu Saharan"
    assert response.known_identities[0].external_thread_id == "164750684061759@lid"


@pytest.mark.asyncio
async def test_reset_workspace_chat_provider_pairing_deletes_session_before_qr(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    connection_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_active=True)
    connection = make_connection()
    connection.id = connection_id
    connection.organization_id = organization_id
    connection.workspace_id = workspace_id
    connection.config = {
        "bridge_base_url": "http://bridge.local",
        "bridge_user_id": "98619967",
    }
    calls: list[str] = []

    async def require_workspace_admin(session, current_user, org_id, ws_id):
        calls.append(f"admin:{current_user.id}:{org_id}:{ws_id}")

    async def get_connection(*args, **kwargs):
        return connection

    async def delete_whatsapp_bridge_session(target):
        calls.append(f"delete:{target.user_id}")
        return ""

    async def create_whatsapp_bridge_session(target):
        calls.append(f"create:{target.user_id}")
        return ""

    async def request_whatsapp_bridge_qr(target):
        calls.append(f"qr:{target.user_id}")
        return "2@fresh", ""

    async def request_whatsapp_bridge_status(target):
        calls.append(f"status:{target.user_id}")
        return {"connected": True, "logged_in": False}, ""

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_connection", get_connection)
    monkeypatch.setattr(service, "delete_whatsapp_bridge_session", delete_whatsapp_bridge_session)
    monkeypatch.setattr(service, "create_whatsapp_bridge_session", create_whatsapp_bridge_session)
    monkeypatch.setattr(service, "request_whatsapp_bridge_qr", request_whatsapp_bridge_qr)
    monkeypatch.setattr(service, "request_whatsapp_bridge_status", request_whatsapp_bridge_status)

    response = await service.reset_workspace_chat_provider_pairing_qr(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
        connection_id,
    )

    assert response.status == "waiting_for_scan"
    assert response.qr_payload == "2@fresh"
    assert "reset" in response.message.lower()
    assert calls[1:] == [
        "delete:98619967",
        "create:98619967",
        "qr:98619967",
        "status:98619967",
    ]


@pytest.mark.asyncio
async def test_send_whatsapp_local_text_message_reconnects_and_retries_bridge(
    monkeypatch,
) -> None:
    connection = make_connection()
    connection.config = {
        "allow_all_senders": True,
        "bridge_base_url": "http://bridge.local",
        "bridge_user_id": "95273632",
    }

    class FakeBridgeClient:
        requests: list[dict] = []
        send_statuses = [503, 200]

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, *, headers=None, json=None, **kwargs):
            self.requests.append({"url": str(url), "headers": headers or {}, "json": json})
            request = httpx.Request("POST", str(url))
            if str(url).endswith("/sessions"):
                return httpx.Response(200, json={"ok": True}, request=request)
            status = self.send_statuses.pop(0)
            if status == 200:
                return httpx.Response(
                    200,
                    json={"message_id": "wa-reply-1"},
                    request=request,
                )
            return httpx.Response(
                status,
                json={"error": "not connected"},
                request=request,
            )

    async def connection_secret_handle_id(*args, **kwargs):
        return uuid4()

    async def resolve_secret(*args, **kwargs):
        return ResolvedSecret("bridge-secret")

    monkeypatch.setattr(service, "connection_secret_handle_id", connection_secret_handle_id)
    monkeypatch.setattr(service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeBridgeClient)
    monkeypatch.setattr(service, "WHATSAPP_BRIDGE_DELIVERY_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(service, "WHATSAPP_BRIDGE_DELIVERY_RETRY_MAX_SECONDS", 0.0)

    result = await service.send_whatsapp_local_text_message(
        FakeSession(),
        connection,
        chat_id="15551234567@s.whatsapp.net",
        text="done",
        reply_to_message_id="wa-inbound-1",
    )

    assert result == {"message_id": "wa-reply-1"}
    assert [request["url"] for request in FakeBridgeClient.requests] == [
        "http://bridge.local/sessions",
        "http://bridge.local/messages/send",
        "http://bridge.local/sessions",
        "http://bridge.local/messages/send",
    ]
    assert FakeBridgeClient.requests[-1]["headers"] == {
        "X-Wardn-Chat-Provider-Secret": "bridge-secret"
    }


@pytest.mark.asyncio
async def test_pending_approval_reply_text_includes_approval_page(monkeypatch) -> None:
    connection = make_connection()
    approval = AgentToolApproval(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_id=uuid4(),
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        requested_by_id=connection.created_by_id,
        installation_id=uuid4(),
        tool_schema_id=uuid4(),
        tool_call_id="call-1",
        tool_name="search_repositories",
        arguments={"query": "wardn"},
        status="pending",
        result="",
        error="",
    )

    async def latest_pending_tool_approval_by_conversation(*args, **kwargs):
        return approval

    monkeypatch.setattr(
        service.agent_repository,
        "latest_pending_tool_approval_by_conversation",
        latest_pending_tool_approval_by_conversation,
    )

    text = await service.pending_approval_reply_text(
        FakeSession(),
        connection,
        approval.conversation_id,
    )

    assert "I need approval to run search_repositories" in text
    assert (
        f"/org/{connection.organization_id}/workspace/{connection.workspace_id}"
        f"/agents/{approval.agent_id}/approvals/{approval.id}"
    ) in text


@pytest.mark.asyncio
async def test_send_whatsapp_local_text_message_does_not_retry_forbidden_bridge(
    monkeypatch,
) -> None:
    connection = make_connection()
    connection.config = {
        "allow_all_senders": True,
        "bridge_base_url": "http://bridge.local",
        "bridge_user_id": "95273632",
    }

    class FakeBridgeClient:
        requests: list[str] = []

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, **kwargs):
            self.requests.append(str(url))
            request = httpx.Request("POST", str(url))
            if str(url).endswith("/sessions"):
                return httpx.Response(200, json={"ok": True}, request=request)
            return httpx.Response(403, json={"error": "forbidden"}, request=request)

    async def connection_secret_handle_id(*args, **kwargs):
        return uuid4()

    async def resolve_secret(*args, **kwargs):
        return ResolvedSecret("bridge-secret")

    monkeypatch.setattr(service, "connection_secret_handle_id", connection_secret_handle_id)
    monkeypatch.setattr(service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeBridgeClient)

    with pytest.raises(ChatProviderDeliveryError):
        await service.send_whatsapp_local_text_message(
            FakeSession(),
            connection,
            chat_id="15551234567@s.whatsapp.net",
            text="done",
            reply_to_message_id="wa-inbound-1",
        )

    assert FakeBridgeClient.requests == [
        "http://bridge.local/sessions",
        "http://bridge.local/messages/send",
    ]


@pytest.mark.asyncio
async def test_whatsapp_bridge_event_processes_self_chat_message(monkeypatch) -> None:
    connection = make_connection()
    processed: list[service.ProviderTextMessage] = []

    async def process_provider_text_message(*args, **kwargs):
        processed.append(args[2])
        return True

    monkeypatch.setattr(service, "process_provider_text_message", process_provider_text_message)

    response = await service.handle_whatsapp_local_bridge_event(
        FakeSession(),
        connection,
        {
            "type": "message",
            "payload": {
                "id": "bridge-inbound-1",
                "chat_jid": "15551234567@s.whatsapp.net",
                "sender_jid": "15551234567:8@s.whatsapp.net",
                "sender_name": "Asha",
                "text": "summarize workspace",
                "is_from_me": True,
            },
        },
    )

    assert response.received == 1
    assert response.processed == 1
    assert processed[0].event_id == "bridge-inbound-1"
    assert processed[0].external_thread_id == "15551234567@s.whatsapp.net"
    assert processed[0].external_user_id == "15551234567:8@s.whatsapp.net"


@pytest.mark.asyncio
async def test_whatsapp_bridge_event_ignores_outbound_echo(monkeypatch) -> None:
    connection = make_connection()

    async def process_provider_text_message(*args, **kwargs):
        raise AssertionError("outbound bridge echoes must not reach the workspace agent")

    monkeypatch.setattr(service, "process_provider_text_message", process_provider_text_message)

    response = await service.handle_whatsapp_local_bridge_event(
        FakeSession(),
        connection,
        {
            "type": "message",
            "payload": {
                "id": "bridge-echo-1",
                "chat_jid": "15551234567@s.whatsapp.net",
                "sender_jid": "15557654321@s.whatsapp.net",
                "text": "agent reply",
                "is_from_me": True,
            },
        },
    )

    assert response.received == 1
    assert response.ignored == 1


@pytest.mark.asyncio
async def test_create_connection_writes_secret_values_and_attaches_handles(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    store_id = uuid4()
    managed_secret_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_active=True)
    required_scope: list[tuple] = []
    write_calls: list[dict] = []
    handle_payloads: list[object] = []
    validated_secret_ids: list[dict[str, object]] = []
    activated: list[object] = []

    async def require_workspace_admin(session, current_user, org_id, ws_id):
        required_scope.append((current_user.id, org_id, ws_id))

    async def write_secret_values(*args, **kwargs):
        write_calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(managed_secret_id=managed_secret_id)

    async def create_secret_handle(*args, **kwargs):
        handle_payloads.append(args[3])
        return SimpleNamespace(id=uuid4())

    async def validate_secret_handles(*args, **kwargs):
        validated_secret_ids.append(kwargs["secret_handle_ids"])

    async def activate_managed_secret(*args, **kwargs):
        activated.append(args[1])

    async def connection_secret_handle_ids(session, connection):
        return {
            item.purpose: item.secret_handle_id
            for item in session.added
            if isinstance(item, ChatProviderConnectionSecret)
            and item.connection_id == connection.id
        }

    async def list_threads_for_connection(*args, **kwargs):
        return []

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service, "write_secret_values", write_secret_values)
    monkeypatch.setattr(service, "create_secret_handle", create_secret_handle)
    monkeypatch.setattr(service, "validate_secret_handles", validate_secret_handles)
    monkeypatch.setattr(service, "activate_managed_secret", activate_managed_secret)
    monkeypatch.setattr(service, "connection_secret_handle_ids", connection_secret_handle_ids)
    monkeypatch.setattr(
        service.repository,
        "list_threads_for_connection",
        list_threads_for_connection,
    )

    session = FakeSession()
    response = await service.create_workspace_chat_provider_connection(
        session,
        user,
        organization_id,
        workspace_id,
        ChatProviderConnectionCreate(
            provider=service.PROVIDER_WHATSAPP_LOCAL,
            name="Personal WhatsApp",
            externalId="personal-phone",
            secretStoreId=store_id,
            secretValues={
                service.SECRET_WEBHOOK_SECRET: "bridge-secret",
                service.SECRET_OUTBOUND_SECRET: "bridge-secret",
            },
            config={
                "allowAllSenders": True,
                "accountName": "personal-phone",
            },
        ),
    )

    connection = next(item for item in session.added if isinstance(item, ChatProviderConnection))
    connection_secrets = [
        item for item in session.added if isinstance(item, ChatProviderConnectionSecret)
    ]

    assert response.id == connection.id
    assert required_scope == [(user.id, organization_id, workspace_id)]
    assert write_calls[0]["args"][3] == store_id
    assert write_calls[0]["kwargs"]["workspace_id"] == workspace_id
    assert write_calls[0]["kwargs"]["values"] == {
        service.SECRET_OUTBOUND_SECRET: "bridge-secret",
        service.SECRET_WEBHOOK_SECRET: "bridge-secret",
    }
    assert write_calls[0]["kwargs"]["purpose"] == service.CHAT_PROVIDER_SECRET_PURPOSE
    assert write_calls[0]["kwargs"]["owner_type"] == service.CHAT_PROVIDER_SECRET_OWNER_TYPE
    assert write_calls[0]["kwargs"]["owner_id"] == connection.id
    assert {payload.key_name for payload in handle_payloads} == {
        service.SECRET_OUTBOUND_SECRET,
        service.SECRET_WEBHOOK_SECRET,
    }
    assert {secret.purpose for secret in connection_secrets} == {
        service.SECRET_OUTBOUND_SECRET,
        service.SECRET_WEBHOOK_SECRET,
    }
    assert set(validated_secret_ids[0]) == {
        service.SECRET_OUTBOUND_SECRET,
        service.SECRET_WEBHOOK_SECRET,
    }
    assert activated == [managed_secret_id]


@pytest.mark.asyncio
async def test_telegram_webhook_validates_secret_and_processes_text(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_TELEGRAM)
    body = b"""
    {
      "update_id": 123,
      "message": {
        "message_id": 42,
        "from": {"id": 987, "first_name": "Asha"},
        "chat": {"id": 555, "type": "private"},
        "text": "Check workspace health"
      }
    }
    """
    processed: list[service.ProviderTextMessage] = []

    async def active_connection(*args, **kwargs):
        return connection

    async def resolve_secret(*args, **kwargs):
        return ResolvedSecret("webhook-secret")

    async def connection_secret_handle_id(*args, **kwargs):
        return uuid4()

    async def process_provider_text_message(*args, **kwargs):
        processed.append(args[2])
        return True

    monkeypatch.setattr(service, "active_connection", active_connection)
    monkeypatch.setattr(service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(service, "connection_secret_handle_id", connection_secret_handle_id)
    monkeypatch.setattr(service, "process_provider_text_message", process_provider_text_message)

    response = await service.handle_telegram_webhook(
        FakeSession(),
        connection_id=connection.id,
        body=body,
        secret_token_header="webhook-secret",
    )

    assert response.received == 1
    assert response.processed == 1
    assert response.failed == 0
    assert processed[0].external_thread_id == "555"
    assert processed[0].external_user_id == "987"
    assert processed[0].text == "Check workspace health"

    with pytest.raises(ChatProviderWebhookAuthError):
        await service.handle_telegram_webhook(
            FakeSession(),
            connection_id=connection.id,
            body=body,
            secret_token_header="wrong",
        )


@pytest.mark.asyncio
async def test_whatsapp_local_webhook_counts_messages_and_skips_duplicates(
    monkeypatch,
) -> None:
    connection = make_connection()
    body = b"""
    {
      "messages": [
        {
          "messageId": "wa-inbound-1",
          "chatId": "15551234567@s.whatsapp.net",
          "senderId": "15551234567@s.whatsapp.net",
          "senderDisplayName": "Asha",
          "text": "hello"
        },
        {
          "messageId": "wa-image-1",
          "chatId": "15551234567@s.whatsapp.net",
          "senderId": "15551234567@s.whatsapp.net",
          "type": "image"
        }
      ]
    }
    """
    processed_texts: list[str] = []

    async def active_connection(*args, **kwargs):
        return connection

    async def resolve_secret(*args, **kwargs):
        return ResolvedSecret("bridge-secret")

    async def connection_secret_handle_id(*args, **kwargs):
        return uuid4()

    async def record_unsupported_provider_message(*args, **kwargs):
        return False

    async def process_provider_text_message(*args, **kwargs):
        processed_texts.append(args[2].text)
        return True

    monkeypatch.setattr(service, "active_connection", active_connection)
    monkeypatch.setattr(service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(service, "connection_secret_handle_id", connection_secret_handle_id)
    monkeypatch.setattr(
        service,
        "record_unsupported_provider_message",
        record_unsupported_provider_message,
    )
    monkeypatch.setattr(service, "process_provider_text_message", process_provider_text_message)

    response = await service.handle_whatsapp_local_webhook(
        FakeSession(),
        connection_id=connection.id,
        body=body,
        secret_header="bridge-secret",
    )

    assert response.received == 2
    assert response.processed == 1
    assert response.duplicates == 1
    assert response.failed == 0
    assert processed_texts == ["hello"]


@pytest.mark.asyncio
async def test_process_provider_text_message_uses_workspace_agent_and_sends_reply(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="15551234567@s.whatsapp.net",
        external_user_id="15551234567@s.whatsapp.net",
        external_user_display_name="Asha",
    )
    conversation_id = thread.conversation_id
    agent_id = uuid4()
    captured_chat = SimpleNamespace(payload=None, committed_before_stream=False, trigger_type="")

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        captured_chat.payload = args[4]
        captured_chat.trigger_type = kwargs["trigger_type"]

        async def stream():
            captured_chat.committed_before_stream = fake_session.commits == 1
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return stream()

    async def latest_assistant_text(*args, **kwargs):
        return "Workspace looks healthy."

    async def send_provider_text_message(*args, **kwargs):
        return {"messageId": "wa-reply-1"}

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_text", latest_assistant_text)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="What changed today?",
            raw={"messageId": "wa-inbound-1"},
        ),
    )

    inbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.external_event_id == "wa-inbound-1"
    )
    outbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.external_event_id == "wa-reply-1"
    )

    assert processed
    assert fake_session.commits == 1
    assert captured_chat.committed_before_stream
    assert captured_chat.trigger_type == "whatsapp"
    assert captured_chat.payload.id == str(conversation_id)
    assert captured_chat.payload.messages[0].parts == [
        {"type": "text", "text": "What changed today?"}
    ]
    assert inbound_event.status == "processed"
    assert inbound_event.thread_id == thread.id
    assert outbound_event.status == "sent"


@pytest.mark.asyncio
async def test_process_provider_text_message_sends_whatsapp_typing_indicator(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    connection.config = {
        "allow_all_senders": True,
        "bridge_base_url": "http://bridge.local",
        "bridge_user_id": "95273632",
    }
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="15551234567@s.whatsapp.net",
        external_user_id="15551234567@s.whatsapp.net",
        external_user_display_name="Asha",
    )
    conversation_id = thread.conversation_id
    agent_id = uuid4()
    typing_calls = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return stream()

    async def latest_assistant_text(*args, **kwargs):
        return "Workspace looks healthy."

    async def send_provider_text_message(*args, **kwargs):
        return {"message_id": "wa-reply-1"}

    async def send_provider_typing_target(target, *, typing):
        typing_calls.append(
            (
                typing,
                target.endpoint,
                target.active_payload if typing else target.idle_payload,
            )
        )

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_text", latest_assistant_text)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)
    monkeypatch.setattr(service, "send_provider_typing_target", send_provider_typing_target)
    monkeypatch.setattr(service, "PROVIDER_TYPING_REFRESH_SECONDS", 60.0)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-typing-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="What changed today?",
            raw={"messageId": "wa-inbound-typing-1"},
        ),
    )

    assert processed
    assert typing_calls == [
        (
            True,
            "http://bridge.local/messages/typing",
            {
                "user_id": 95273632,
                "chat_jid": "15551234567@s.whatsapp.net",
                "typing": True,
            },
        ),
        (
            False,
            "http://bridge.local/messages/typing",
            {
                "user_id": 95273632,
                "chat_jid": "15551234567@s.whatsapp.net",
                "typing": False,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_process_provider_text_message_ignores_disallowed_sender(monkeypatch) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    connection.config = {
        "allow_all_senders": False,
        "allowed_sender_ids": ["15550000000@s.whatsapp.net"],
        "outbound_webhook_url": "http://bridge.local/send",
    }

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        raise AssertionError("disallowed sender must not reach the workspace agent")

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="What changed today?",
            raw={"messageId": "wa-inbound-1"},
        ),
    )
    inbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.external_event_id == "wa-inbound-1"
    )

    assert processed
    assert fake_session.commits == 0
    assert inbound_event.status == "ignored"
    assert inbound_event.error == "WhatsApp sender is not allowed"


@pytest.mark.asyncio
async def test_provider_thread_conversation_creates_provider_thread(monkeypatch) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    agent_id = uuid4()
    conversation_id = uuid4()

    async def get_thread(*args, **kwargs):
        return None

    async def quick_start_workspace_agent(*args, **kwargs):
        now = datetime(2026, 8, 2, tzinfo=UTC)
        return AgentConversationResponse(
            agent=AgentRead(
                id=agent_id,
                organizationId=connection.organization_id,
                workspaceId=connection.workspace_id,
                createdById=actor.id,
                providerCredentialId=uuid4(),
                name="Workspace Assistant",
                description="",
                instructions="",
                scope="workspace",
                modelName="gpt-5.5",
                skillIds=[],
                isActive=True,
                serverCount=0,
                toolCount=0,
                createdAt=now,
                updatedAt=now,
            ),
            conversation=WorkspaceConversationRead(
                id=conversation_id,
                organizationId=connection.organization_id,
                workspaceId=connection.workspace_id,
                agentId=agent_id,
                createdById=actor.id,
                title="New chat",
                isActive=True,
                createdAt=now,
                updatedAt=now,
            ),
            messages=[],
        )

    async def get_workspace_conversation(*args, **kwargs):
        return WorkspaceConversation(
            id=conversation_id,
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            agent_id=agent_id,
            created_by_id=actor.id,
            title="New chat",
            is_active=True,
        )

    monkeypatch.setattr(service.repository, "get_thread", get_thread)
    monkeypatch.setattr(
        service.agent_service,
        "quick_start_workspace_agent",
        quick_start_workspace_agent,
    )
    monkeypatch.setattr(
        service.agent_repository,
        "get_workspace_conversation",
        get_workspace_conversation,
    )

    result = await service.provider_thread_conversation(
        fake_session,
        connection,
        actor,
        service.ProviderTextMessage(
            event_id="wa-inbound-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="hello",
            raw={},
        ),
    )
    thread, returned_conversation_id, returned_agent_id = result

    assert returned_conversation_id == conversation_id
    assert returned_agent_id == agent_id
    assert thread.external_thread_id == "15551234567@s.whatsapp.net"
    assert thread.external_user_display_name == "Asha"
    assert thread.provider_metadata == {"provider": service.PROVIDER_WHATSAPP_LOCAL}
    assert thread in fake_session.added


@pytest.mark.asyncio
async def test_validate_secret_handles_requires_telegram_access_token() -> None:
    with pytest.raises(InvalidChatProviderConnectionError):
        await service.validate_secret_handles(
            FakeSession(),
            organization_id=uuid4(),
            workspace_id=uuid4(),
            provider=service.PROVIDER_TELEGRAM,
            secret_handle_ids={service.SECRET_WEBHOOK_SECRET: uuid4()},
        )
