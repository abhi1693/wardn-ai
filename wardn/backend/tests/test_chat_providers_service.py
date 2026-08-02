from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.agents.models import WorkspaceConversation
from app.modules.agents.schemas import (
    AgentConversationResponse,
    AgentRead,
    WorkspaceConversationRead,
)
from app.modules.chat_providers import service
from app.modules.chat_providers.exceptions import (
    ChatProviderWebhookAuthError,
    InvalidChatProviderConnectionError,
)
from app.modules.chat_providers.models import (
    ChatProviderConnection,
    ChatProviderConnectionSecret,
    ChatProviderEvent,
    ChatProviderThread,
)
from app.modules.chat_providers.schemas import (
    ChatProviderConnectionCreate,
    ChatProviderTestMessageRequest,
)
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
        {"connected": True, "phone_number": "+15551234567"}
    )

    assert status == "connected"
    assert message == "WhatsApp session is connected."
    assert phone_number == "+15551234567"


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

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service, "write_secret_values", write_secret_values)
    monkeypatch.setattr(service, "create_secret_handle", create_secret_handle)
    monkeypatch.setattr(service, "validate_secret_handles", validate_secret_handles)
    monkeypatch.setattr(service, "activate_managed_secret", activate_managed_secret)
    monkeypatch.setattr(service, "connection_secret_handle_ids", connection_secret_handle_ids)

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
    captured_chat = SimpleNamespace(payload=None, committed_before_stream=False)

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        captured_chat.payload = args[4]

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
    assert captured_chat.payload.id == str(conversation_id)
    assert captured_chat.payload.messages[0].parts == [
        {"type": "text", "text": "What changed today?"}
    ]
    assert inbound_event.status == "processed"
    assert inbound_event.thread_id == thread.id
    assert outbound_event.status == "sent"


@pytest.mark.asyncio
async def test_process_provider_text_message_ignores_disallowed_sender(monkeypatch) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    connection.config = {
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
async def test_test_workspace_chat_provider_connection_returns_reply_without_delivery(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    user = User(id=uuid4(), email="admin@example.com", is_active=True)
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="test-thread",
        external_user_id=str(user.id),
        external_user_display_name="Wardn test",
    )
    agent_id = uuid4()
    sent: list[object] = []

    async def require_workspace_admin(*args, **kwargs):
        return None

    async def get_connection(*args, **kwargs):
        return connection

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, thread.conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return stream()

    async def latest_assistant_text(*args, **kwargs):
        return "The workspace is ready."

    async def send_provider_text_message(*args, **kwargs):
        sent.append(args)
        return {}

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_connection", get_connection)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_text", latest_assistant_text)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    response = await service.test_workspace_chat_provider_connection(
        fake_session,
        user,
        connection.organization_id,
        connection.workspace_id,
        connection.id,
        ChatProviderTestMessageRequest(
            text="Check this provider",
            externalThreadId="test-thread",
            externalUserId=str(user.id),
            externalUserDisplayName="Wardn test",
        ),
    )

    outbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "outbound"
    )

    assert response.ok
    assert response.processed
    assert response.reply_text == "The workspace is ready."
    assert response.conversation_id == thread.conversation_id
    assert outbound_event.status == "processed"
    assert outbound_event.event_type == "message.test_reply"
    assert outbound_event.payload["test"]["delivery"] == "skipped"
    assert sent == []


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
