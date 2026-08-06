from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.modules.agents.models import (
    AgentRun,
    AgentToolApproval,
    ConversationMessage,
    WorkspaceConversation,
)
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
from app.modules.organizations.models import OrganizationMembership, WorkspaceMembership
from app.modules.secrets.provider import ResolvedSecret
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushes += 1
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
        return SimpleNamespace(scalar_one_or_none=lambda: None)


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


def test_parse_agent_stream_chunk_extracts_progress_events() -> None:
    events = service.parse_agent_stream_chunk(
        'data: {"type":"data-tool-activity","data":{"toolName":"Search","status":"running"}}\n\n'
        'data: {"type":"finish","finishReason":"stop"}\n\n'
    )

    assert events == [
        {
            "type": "data-tool-activity",
            "data": {"toolName": "Search", "status": "running"},
        },
        {"type": "finish", "finishReason": "stop"},
    ]


@pytest.mark.asyncio
async def test_send_provider_progress_records_whatsapp_reaction(monkeypatch) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    connection.config = {
        "allow_all_senders": True,
        "bridge_base_url": "http://bridge.local",
        "bridge_user_id": "95273632",
    }
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
    calls: list[dict[str, str]] = []

    async def send_whatsapp_bridge_reaction(*args, **kwargs):
        calls.append(kwargs)
        return {"message_id": "wa-reaction-1"}

    monkeypatch.setattr(service, "send_whatsapp_bridge_reaction", send_whatsapp_bridge_reaction)

    notifier = service.ProviderProgressNotifier(
        connection=connection,
        thread=thread,
        inbound_event_id="wa-inbound-1",
        external_thread_id=thread.external_thread_id,
        agent_run_id=uuid4(),
    )
    await service.send_provider_progress(fake_session, notifier, state="accepted")

    progress_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "status"
    )

    assert calls == [
        {
            "external_thread_id": "15551234567@s.whatsapp.net",
            "message_id": "wa-inbound-1",
            "emoji": "\U0001f440",
        }
    ]
    assert progress_event.event_type == "message.progress"
    assert progress_event.status == "sent"
    assert progress_event.payload["providerProgressState"] == "accepted"
    assert progress_event.payload["agentRunId"] == str(notifier.agent_run_id)


@pytest.mark.asyncio
async def test_send_provider_progress_updates_single_telegram_status_message(monkeypatch) -> None:
    fake_session = FakeSession()
    connection = make_connection(service.PROVIDER_TELEGRAM)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="555",
        external_user_id="987",
        external_user_display_name="Asha",
    )
    calls: list[tuple[str, dict[str, object]]] = []

    async def send_telegram_text_message(*args, **kwargs):
        calls.append(("send", kwargs))
        return {"result": {"message_id": 42, "chat": {"id": "555"}}}

    async def send_telegram_edit_message(*args, **kwargs):
        calls.append(("edit", kwargs))
        return {"result": {"message_id": 42, "chat": {"id": "555"}}}

    monkeypatch.setattr(service, "send_telegram_text_message", send_telegram_text_message)
    monkeypatch.setattr(service, "send_telegram_edit_message", send_telegram_edit_message)

    notifier = service.ProviderProgressNotifier(
        connection=connection,
        thread=thread,
        inbound_event_id="update:123",
        external_thread_id=thread.external_thread_id,
    )
    await service.send_provider_progress(fake_session, notifier, state="accepted")
    await service.send_provider_progress(fake_session, notifier, state="done", terminal=True)

    assert calls == [
        ("send", {"chat_id": "555", "text": "Working on it."}),
        (
            "edit",
            {
                "external_message_id": "message:555:42",
                "text": "Done.",
            },
        ),
    ]
    assert notifier.status_message_external_id == "message:555:42"


@pytest.mark.asyncio
async def test_send_provider_progress_updates_single_slack_status_message(monkeypatch) -> None:
    fake_session = FakeSession()
    connection = make_connection(service.PROVIDER_SLACK)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="T123:C123:1700000000.000100",
        external_user_id="U123",
        external_user_display_name="Asha",
    )
    calls: list[tuple[str, dict[str, object]]] = []

    async def send_slack_text_message(*args, **kwargs):
        calls.append(("send", kwargs))
        return {"ok": True, "channel": "C123", "ts": "1700000000.000200"}

    async def send_slack_update_message(*args, **kwargs):
        calls.append(("edit", kwargs))
        return {"ok": True, "channel": "C123", "ts": "1700000000.000200"}

    monkeypatch.setattr(service, "send_slack_text_message", send_slack_text_message)
    monkeypatch.setattr(service, "send_slack_update_message", send_slack_update_message)

    notifier = service.ProviderProgressNotifier(
        connection=connection,
        thread=thread,
        inbound_event_id="event:T123:C123:1700000000.000100",
        external_thread_id=thread.external_thread_id,
    )
    await service.send_provider_progress(fake_session, notifier, state="accepted")
    await service.send_provider_progress(fake_session, notifier, state="done", terminal=True)

    assert calls == [
        (
            "send",
            {
                "external_thread_id": "T123:C123:1700000000.000100",
                "text": "Working on it.",
            },
        ),
        (
            "edit",
            {
                "external_message_id": "message:C123:1700000000.000200",
                "text": "Done.",
            },
        ),
    ]
    assert notifier.status_message_external_id == "message:C123:1700000000.000200"


@pytest.mark.asyncio
async def test_provider_progress_preserves_waiting_approval_on_successful_finish(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection(service.PROVIDER_SLACK)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="T123:C123:1700000000.000100",
        external_user_id="U123",
        external_user_display_name="Asha",
    )
    states: list[str] = []

    async def send_provider_progress(*args, **kwargs):
        states.append(kwargs["state"])

    monkeypatch.setattr(service, "send_provider_progress", send_provider_progress)

    notifier = service.ProviderProgressNotifier(
        connection=connection,
        thread=thread,
        inbound_event_id="event:T123:C123:1700000000.000100",
        external_thread_id=thread.external_thread_id,
    )
    await service.observe_provider_agent_stream_chunk(
        fake_session,
        notifier,
        (
            'data: {"type":"data-tool-activity","data":'
            '{"toolName":"Deploy","status":"requires_confirmation"}}\n\n'
            'data: {"type":"finish","finishReason":"stop"}\n\n'
        ),
    )

    assert notifier.paused_for_approval
    assert states == ["waiting_approval"]


@pytest.mark.asyncio
async def test_provider_progress_reports_failed_finish_after_waiting_approval(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection(service.PROVIDER_SLACK)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="T123:C123:1700000000.000100",
        external_user_id="U123",
        external_user_display_name="Asha",
    )
    states: list[str] = []

    async def send_provider_progress(*args, **kwargs):
        states.append(kwargs["state"])

    monkeypatch.setattr(service, "send_provider_progress", send_provider_progress)

    notifier = service.ProviderProgressNotifier(
        connection=connection,
        thread=thread,
        inbound_event_id="event:T123:C123:1700000000.000100",
        external_thread_id=thread.external_thread_id,
    )
    await service.observe_provider_agent_stream_chunk(
        fake_session,
        notifier,
        (
            'data: {"type":"data-tool-activity","data":'
            '{"toolName":"Deploy","status":"requires_confirmation"}}\n\n'
            'data: {"type":"finish","finishReason":"error"}\n\n'
        ),
    )

    assert states == ["waiting_approval", "failed"]


@pytest.mark.asyncio
async def test_deliver_conversation_reply_to_provider_thread_sends_run_assistant(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    conversation_id = uuid4()
    agent_run_id = uuid4()
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=conversation_id,
        external_thread_id="15551234567@s.whatsapp.net",
        external_user_id="15551234567@s.whatsapp.net",
        external_user_display_name="Asha",
        last_external_message_id="wa-inbound-1",
    )
    sent: dict[str, object] = {}

    async def has_provider_reply_for_agent_run(*args, **kwargs):
        return False

    async def get_thread_connection_for_conversation(*args, **kwargs):
        return thread, connection

    async def latest_assistant_message_for_run(*args, **kwargs):
        assert kwargs["conversation_id"] == conversation_id
        assert kwargs["agent_run_id"] == agent_run_id
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            role="assistant",
            content="Redeploy completed.",
            parts=[{"type": "text", "text": "Redeploy completed."}],
            sequence=2,
        )

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

    async def send_provider_text_message(*args, **kwargs):
        sent.update(kwargs)
        return {"id": "wa-outbound-1"}

    monkeypatch.setattr(
        service.repository,
        "has_provider_reply_for_agent_run",
        has_provider_reply_for_agent_run,
    )
    monkeypatch.setattr(
        service.repository,
        "get_thread_connection_for_conversation",
        get_thread_connection_for_conversation,
    )
    monkeypatch.setattr(
        service.agent_repository,
        "latest_assistant_message_for_run",
        latest_assistant_message_for_run,
    )
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    await service.deliver_conversation_reply_to_provider_thread(
        fake_session,
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        external_event_id_prefix="approval-resume",
    )

    assert sent["external_thread_id"] == thread.external_thread_id
    assert sent["text"] == "Redeploy completed."
    assert sent["reply_to_message_id"] == "wa-inbound-1"
    outbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "outbound"
    )
    assert outbound_event.status == "sent"
    assert outbound_event.event_type == "message.text"
    assert outbound_event.payload["agentRunId"] == str(agent_run_id)
    assert outbound_event.payload["providerReplyKind"] == "assistant"
    assert outbound_event.payload[connection.provider] == {"id": "wa-outbound-1"}


@pytest.mark.asyncio
async def test_deliver_conversation_reply_to_provider_thread_skips_existing_reply(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()

    async def has_provider_reply_for_agent_run(*args, **kwargs):
        return True

    async def send_provider_text_message(*args, **kwargs):
        raise AssertionError("duplicate provider replies must not be sent")

    monkeypatch.setattr(
        service.repository,
        "has_provider_reply_for_agent_run",
        has_provider_reply_for_agent_run,
    )
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    await service.deliver_conversation_reply_to_provider_thread(
        fake_session,
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        external_event_id_prefix="approval-resume",
    )

    assert fake_session.added == []


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


def test_provider_config_normalizes_approval_routes() -> None:
    user_id = uuid4()

    config = service.normalize_connection_config(
        service.PROVIDER_WHATSAPP_LOCAL,
        {
            "approvalRoutes": [
                {
                    "routeType": "workspace_member",
                    "userId": str(user_id),
                    "displayName": "Workspace Owner",
                },
                {
                    "routeType": "workspace_member",
                    "userId": str(user_id),
                    "displayName": "Duplicate",
                },
                {
                    "routeType": "chat_provider",
                    "connectionId": str(uuid4()),
                    "externalThreadId": "legacy@s.whatsapp.net",
                    "displayName": "Legacy contact",
                },
                {"routeType": "chat"},
            ]
        },
    )

    assert config["approval_routes"] == [
        {
            "route_type": "workspace_member",
            "user_id": str(user_id),
            "connection_id": None,
            "external_thread_id": "",
            "display_name": "Workspace Owner",
        },
    ]


def test_slack_sender_allowed_accepts_conversation_allow_list() -> None:
    connection = make_connection(service.PROVIDER_SLACK)
    connection.config = {
        "allow_all_senders": False,
        "allowed_chat_ids": ["T123:C123"],
        "allowed_sender_ids": [],
    }

    assert service.sender_allowed(
        connection,
        service.ProviderTextMessage(
            event_id="Ev1",
            external_thread_id="T123:C123:1786026213.981319",
            external_user_id="U123",
            external_user_display_name="Asha",
            text="hi",
            raw={},
        ),
    )


@pytest.mark.asyncio
async def test_workspace_member_responses_include_effective_internal_approvers(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    workspace_member = User(
        id=uuid4(),
        email="member@example.com",
        first_name="Workspace",
        last_name="Member",
        is_active=True,
    )
    organization_owner = User(
        id=uuid4(),
        email="owner@example.com",
        first_name="Organization",
        last_name="Owner",
        is_active=True,
    )
    superuser = User(
        id=uuid4(),
        email="super@example.com",
        first_name="Wardn",
        last_name="Admin",
        is_active=True,
        is_superuser=True,
    )
    workspace_membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=workspace_member.id,
        role="member",
        is_active=True,
    )
    organization_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=organization_owner.id,
        role="owner",
        is_active=True,
    )

    async def list_workspace_members(*args, **kwargs):
        return [(workspace_membership, workspace_member)]

    async def list_organization_admin_members(*args, **kwargs):
        return [(organization_membership, organization_owner)]

    async def list_active_superusers(*args, **kwargs):
        return [superuser]

    monkeypatch.setattr(
        service.organizations_repository,
        "list_workspace_members",
        list_workspace_members,
    )
    monkeypatch.setattr(
        service.organizations_repository,
        "list_organization_admin_members",
        list_organization_admin_members,
    )
    monkeypatch.setattr(service, "list_active_superusers", list_active_superusers)

    members = await service.workspace_member_responses(
        FakeSession(),
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    assert [(member.email, member.role) for member in members] == [
        ("owner@example.com", "owner"),
        ("super@example.com", "owner"),
        ("member@example.com", "member"),
    ]


@pytest.mark.asyncio
async def test_workspace_member_responses_promote_duplicate_effective_roles(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(
        id=uuid4(),
        email="owner@example.com",
        first_name="Workspace",
        last_name="Owner",
        is_active=True,
    )
    workspace_membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=user.id,
        role="member",
        is_active=True,
    )
    organization_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def list_workspace_members(*args, **kwargs):
        return [(workspace_membership, user)]

    async def list_organization_admin_members(*args, **kwargs):
        return [(organization_membership, user)]

    async def list_active_superusers(*args, **kwargs):
        return []

    monkeypatch.setattr(
        service.organizations_repository,
        "list_workspace_members",
        list_workspace_members,
    )
    monkeypatch.setattr(
        service.organizations_repository,
        "list_organization_admin_members",
        list_organization_admin_members,
    )
    monkeypatch.setattr(service, "list_active_superusers", list_active_superusers)

    members = await service.workspace_member_responses(
        FakeSession(),
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    assert [(member.email, member.role) for member in members] == [
        ("owner@example.com", "owner"),
    ]


@pytest.mark.asyncio
async def test_validate_approval_routes_accepts_superuser_without_membership(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    approver = User(id=uuid4(), email="super@example.com", is_active=True, is_superuser=True)

    async def get_user_by_id(*args, **kwargs):
        return approver

    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)

    await service.validate_approval_routes(
        FakeSession(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        routes=[
            {
                "route_type": "workspace_member",
                "external_thread_id": "15551234567@s.whatsapp.net",
                "user_id": str(approver.id),
            }
        ],
    )


@pytest.mark.asyncio
async def test_validate_approval_routes_accepts_organization_admin_without_workspace_membership(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    approver = User(id=uuid4(), email="admin@example.com", is_active=True)
    organization_membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=approver.id,
        role="admin",
        is_active=True,
    )

    async def get_user_by_id(*args, **kwargs):
        return approver

    async def get_organization_membership(*args, **kwargs):
        return organization_membership

    async def get_workspace_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(
        service.organizations_repository,
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(
        service.organizations_repository,
        "get_workspace_membership",
        get_workspace_membership,
    )

    await service.validate_approval_routes(
        FakeSession(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        routes=[
            {
                "route_type": "workspace_member",
                "external_thread_id": "15551234567@s.whatsapp.net",
                "user_id": str(approver.id),
            }
        ],
    )


@pytest.mark.asyncio
async def test_validate_approval_routes_requires_linked_provider_thread(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    approver = User(id=uuid4(), email="owner@example.com", is_active=True, is_superuser=True)

    async def get_user_by_id(*args, **kwargs):
        return approver

    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)

    with pytest.raises(InvalidChatProviderConnectionError, match="provider thread"):
        await service.validate_approval_routes(
            FakeSession(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            routes=[
                {
                    "route_type": "workspace_member",
                    "user_id": str(approver.id),
                }
            ],
        )


@pytest.mark.asyncio
async def test_validate_approval_routes_rejects_slack_channel_thread(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_SLACK)
    connection.external_id = "T123"
    connection.config = {"allow_all_senders": True, "team_id": "T123"}
    approver = User(id=uuid4(), email="owner@example.com", is_active=True, is_superuser=True)
    linked_thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        external_thread_id="T123:C123:1786026213.981319",
        external_user_id="U123",
        external_user_display_name="Asha",
    )

    async def get_user_by_id(*args, **kwargs):
        return approver

    async def get_thread(*args, **kwargs):
        return linked_thread

    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(service.repository, "get_thread", get_thread)

    with pytest.raises(InvalidChatProviderConnectionError, match="direct message"):
        await service.validate_approval_routes(
            FakeSession(),
            connection=connection,
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            routes=[
                {
                    "route_type": "workspace_member",
                    "external_thread_id": linked_thread.external_thread_id,
                    "user_id": str(approver.id),
                }
            ],
        )


@pytest.mark.asyncio
async def test_validate_approval_routes_accepts_slack_dm_conversation(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_SLACK)
    connection.external_id = "T123"
    connection.config = {"allow_all_senders": True, "team_id": "T123"}
    approver = User(id=uuid4(), email="owner@example.com", is_active=True, is_superuser=True)
    linked_thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        external_thread_id="T123:D123:1786026685.810419",
        external_user_id="U123",
        external_user_display_name="Asha",
    )

    async def get_user_by_id(*args, **kwargs):
        return approver

    async def get_thread_by_external_thread_prefix(*args, **kwargs):
        return linked_thread

    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(
        service.repository,
        "get_thread_by_external_thread_prefix",
        get_thread_by_external_thread_prefix,
    )

    await service.validate_approval_routes(
        FakeSession(),
        connection=connection,
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        routes=[
            {
                "route_type": "workspace_member",
                "external_thread_id": "T123:D123",
                "user_id": str(approver.id),
            }
        ],
    )


@pytest.mark.asyncio
async def test_validate_approval_routes_rejects_external_or_inactive_users(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    approver = User(id=uuid4(), email="external@example.com", is_active=True)

    async def get_user_by_id(*args, **kwargs):
        return approver

    async def get_organization_membership(*args, **kwargs):
        return None

    async def get_workspace_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(
        service.organizations_repository,
        "get_organization_membership",
        get_organization_membership,
    )
    monkeypatch.setattr(
        service.organizations_repository,
        "get_workspace_membership",
        get_workspace_membership,
    )

    with pytest.raises(InvalidChatProviderConnectionError):
        await service.validate_approval_routes(
            FakeSession(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            routes=[
                {
                    "route_type": "workspace_member",
                    "external_thread_id": "15551234567@s.whatsapp.net",
                    "user_id": str(approver.id),
                }
            ],
        )


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
async def test_connection_response_hydrates_slack_identities_without_flush(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_SLACK)
    connection.name = "Home Slack"
    connection.external_id = "T0TEAM"
    now = datetime(2026, 8, 6, tzinfo=UTC)
    connection.created_at = now
    connection.updated_at = now
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id="T0TEAM:D0DM",
        external_user_id="U0USER",
        external_user_display_name="",
        provider_metadata={},
    )
    thread.created_at = now
    thread.updated_at = now
    fake_session = FakeSession()

    async def connection_secret_handle_ids(*args, **kwargs):
        return {}

    async def list_threads_for_connection(*args, **kwargs):
        return [thread]

    async def slack_bot_token_value(*args, **kwargs):
        return "xoxb-token"

    def response_json(response):
        if response.request.url.path.endswith("/users.info"):
            return {
                "ok": True,
                "user": {
                    "profile": {
                        "display_name": "Abhimanyu",
                        "real_name": "Abhimanyu Saharan",
                    },
                    "name": "abhimanyu",
                },
            }
        return {"ok": True, "channel": {"name": "wardn-ai"}}

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={}, request=httpx.Request("GET", url))

    monkeypatch.setattr(service, "connection_secret_handle_ids", connection_secret_handle_ids)
    monkeypatch.setattr(
        service.repository,
        "list_threads_for_connection",
        list_threads_for_connection,
    )
    monkeypatch.setattr(service, "slack_bot_token_value", slack_bot_token_value)
    monkeypatch.setattr(service, "response_json", response_json)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    response = await service.connection_response(fake_session, connection)

    assert fake_session.flushes == 0
    assert response.known_identities[0].display_name == "Abhimanyu Saharan"
    assert response.known_identities[0].provider_metadata == {
        "slack_channel_display_name": "#wardn-ai"
    }
    assert thread.external_user_display_name == "Abhimanyu Saharan"


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
async def test_send_slack_text_message_posts_thread_reply(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_SLACK)

    class FakeSlackClient:
        requests: list[dict] = []

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, *, headers=None, json=None, **kwargs):
            self.requests.append({"url": str(url), "headers": headers or {}, "json": json})
            request = httpx.Request("POST", str(url))
            return httpx.Response(
                200,
                json={"ok": True, "channel": "C123", "ts": "1700000001.000200"},
                request=request,
            )

    async def connection_secret_handle_id(*args, **kwargs):
        return uuid4()

    async def resolve_secret(*args, **kwargs):
        return ResolvedSecret("xoxb-token")

    monkeypatch.setattr(service, "connection_secret_handle_id", connection_secret_handle_id)
    monkeypatch.setattr(service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeSlackClient)

    result = await service.send_slack_text_message(
        FakeSession(),
        connection,
        external_thread_id="T123:C123:1700000000.000100",
        text="done",
    )

    assert result == {"ok": True, "channel": "C123", "ts": "1700000001.000200"}
    assert FakeSlackClient.requests == [
        {
            "url": "https://slack.com/api/chat.postMessage",
            "headers": {"Authorization": "Bearer xoxb-token"},
            "json": {
                "channel": "C123",
                "text": "done",
                "thread_ts": "1700000000.000100",
                "unfurl_links": False,
                "unfurl_media": False,
            },
        }
    ]


@pytest.mark.asyncio
async def test_send_slack_text_message_posts_dm_without_thread(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_SLACK)

    class FakeSlackClient:
        requests: list[dict] = []

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, *, headers=None, json=None, **kwargs):
            self.requests.append({"url": str(url), "headers": headers or {}, "json": json})
            request = httpx.Request("POST", str(url))
            return httpx.Response(200, json={"ok": True, "channel": "D123"}, request=request)

    async def connection_secret_handle_id(*args, **kwargs):
        return uuid4()

    async def resolve_secret(*args, **kwargs):
        return ResolvedSecret("xoxb-token")

    monkeypatch.setattr(service, "connection_secret_handle_id", connection_secret_handle_id)
    monkeypatch.setattr(service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeSlackClient)

    result = await service.send_slack_text_message(
        FakeSession(),
        connection,
        external_thread_id="T123:D123",
        text="approval",
    )

    assert result == {"ok": True, "channel": "D123"}
    assert FakeSlackClient.requests[0]["json"] == {
        "channel": "D123",
        "text": "approval",
        "unfurl_links": False,
        "unfurl_media": False,
    }


@pytest.mark.asyncio
async def test_handle_slack_socket_mode_event_rejects_wrong_team(monkeypatch) -> None:
    connection = make_connection(service.PROVIDER_SLACK)
    connection.external_id = "T123"
    connection.config = {"allow_all_senders": True, "team_id": "T123"}

    async def active_connection(*args, **kwargs):
        return connection

    async def process_provider_text_message(*args, **kwargs):
        raise AssertionError("wrong-team Slack events must not be processed")

    monkeypatch.setattr(service, "active_connection", active_connection)
    monkeypatch.setattr(service, "process_provider_text_message", process_provider_text_message)

    with pytest.raises(ChatProviderWebhookAuthError):
        await service.handle_slack_socket_mode_event(
            FakeSession(),
            connection_id=connection.id,
            payload={
                "type": "event_callback",
                "team_id": "T999",
                "event_id": "Ev1",
                "event": {
                    "type": "app_mention",
                    "team": "T999",
                    "channel": "C1",
                    "user": "U1",
                    "text": "<@B1> hi",
                    "ts": "1700000000.000100",
                },
            },
        )


@pytest.mark.asyncio
async def test_pending_approval_reply_text_does_not_include_approval_page(monkeypatch) -> None:
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

    assert "workspace approval" in text
    assert "Open this Wardn approval page" not in text
    assert (
        f"/org/{connection.organization_id}/workspace/{connection.workspace_id}"
        f"/agents/{approval.agent_id}/approvals/{approval.id}"
    ) not in text


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
    captured_chat = SimpleNamespace(
        payload=None,
        committed_before_stream=False,
        previous_agent_run_id=None,
        trigger_type="",
    )
    previous_agent_run = AgentRun(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        trigger_type="whatsapp",
        status="succeeded",
        started_at=datetime(2026, 8, 2, 8, 0, tzinfo=UTC),
        error="",
    )

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        captured_chat.payload = args[4]
        captured_chat.previous_agent_run_id = kwargs["previous_agent_run_id"]
        captured_chat.trigger_type = kwargs["trigger_type"]

        async def stream():
            captured_chat.committed_before_stream = fake_session.commits == 1
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return stream()

    assistant_agent_run_id = uuid4()

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=assistant_agent_run_id,
            role="assistant",
            content="Workspace looks healthy.",
            parts=[{"type": "text", "text": "Workspace looks healthy."}],
            sequence=2,
        )

    async def send_provider_text_message(*args, **kwargs):
        return {"messageId": "wa-reply-1"}

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

    async def latest_agent_run_for_conversation(*args, **kwargs):
        assert kwargs["organization_id"] == connection.organization_id
        assert kwargs["workspace_id"] == connection.workspace_id
        assert kwargs["conversation_id"] == conversation_id
        assert kwargs["trigger_type"] == "whatsapp"
        return previous_agent_run

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(
        service.agent_repository,
        "latest_agent_run_for_conversation",
        latest_agent_run_for_conversation,
    )
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
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
    assert captured_chat.previous_agent_run_id == previous_agent_run.id
    assert captured_chat.trigger_type == "whatsapp"
    assert captured_chat.payload.id == str(conversation_id)
    assert captured_chat.payload.messages[0].parts == [
        {"type": "text", "text": "What changed today?"}
    ]
    assert inbound_event.status == "processed"
    assert inbound_event.thread_id == thread.id
    assert outbound_event.status == "sent"
    assert outbound_event.payload["agentRunId"] == str(assistant_agent_run_id)


@pytest.mark.asyncio
async def test_process_provider_text_message_reports_unlinked_workspace_member_approval(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    requester_thread_id = "15551234567@s.whatsapp.net"
    approver_user_id = uuid4()
    connection.config = {
        **connection.config,
        "approval_routes": [
            {
                "route_type": "workspace_member",
                "user_id": str(approver_user_id),
                "display_name": "Workspace Owner",
            }
        ],
    }
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id=requester_thread_id,
        external_user_id=requester_thread_id,
        external_user_display_name="Outside User",
    )
    conversation_id = thread.conversation_id
    agent_id = uuid4()
    agent_run_id = uuid4()
    approval = AgentToolApproval(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        requested_by_id=connection.created_by_id,
        installation_id=uuid4(),
        tool_schema_id=uuid4(),
        tool_call_id="call-1",
        tool_name="restart_workload",
        arguments={"name": "api"},
        status="pending",
        result="",
        error="",
    )
    sent_messages: list[tuple[str, str]] = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"tool_approval"}\n\n'

        return stream()

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            role="assistant",
            content="",
            parts=[],
            sequence=2,
        )

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

    async def latest_pending_approval(*args, **kwargs):
        return approval

    async def send_provider_text_message(*args, **kwargs):
        sent_messages.append((kwargs["external_thread_id"], kwargs["text"]))
        return {"message_id": f"msg-{len(sent_messages)}"}

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
    monkeypatch.setattr(service, "latest_pending_approval", latest_pending_approval)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-approval-1",
            external_thread_id=requester_thread_id,
            external_user_id=requester_thread_id,
            external_user_display_name="Outside User",
            text="Restart the workload",
            raw={"messageId": "wa-inbound-approval-1"},
        ),
    )

    assert processed
    assert sent_messages == [
        (requester_thread_id, service.PROVIDER_APPROVAL_PENDING_UNDELIVERED_REPLY)
    ]
    assert "Open this Wardn approval page" not in sent_messages[0][1]
    approval_events = [
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.event_type == "approval.request"
    ]
    assert len(approval_events) == 1
    assert approval_events[0].thread_id is None
    assert approval_events[0].status == "failed"
    assert "linked approver thread" in approval_events[0].error
    assert approval_events[0].payload["approvalId"] == str(approval.id)
    assert approval_events[0].payload["agentRunId"] == str(agent_run_id)
    assert approval_events[0].payload["externalDelivery"] is False
    assert approval_events[0].payload["routeType"] == "workspace_member"
    assert approval_events[0].payload["userId"] == str(approver_user_id)
    assert "Open this Wardn approval page" in approval_events[0].payload["message"]


@pytest.mark.asyncio
async def test_process_provider_text_message_sends_approval_to_linked_workspace_member_thread(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    requester_thread_id = "15551234567@s.whatsapp.net"
    approver_thread_id = "15557654321@s.whatsapp.net"
    approver_user_id = uuid4()
    connection.config = {
        **connection.config,
        "approval_routes": [
            {
                "route_type": "workspace_member",
                "user_id": str(approver_user_id),
                "external_thread_id": approver_thread_id,
                "display_name": "Workspace Owner",
            }
        ],
    }
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    requester_thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id=requester_thread_id,
        external_user_id=requester_thread_id,
        external_user_display_name="Outside User",
    )
    approver_thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id=approver_thread_id,
        external_user_id=approver_thread_id,
        external_user_display_name="Workspace Owner",
    )
    conversation_id = requester_thread.conversation_id
    agent_id = uuid4()
    agent_run_id = uuid4()
    approval = AgentToolApproval(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        requested_by_id=connection.created_by_id,
        installation_id=uuid4(),
        tool_schema_id=uuid4(),
        tool_call_id="call-1",
        tool_name="restart_workload",
        arguments={"name": "api"},
        status="pending",
        result="",
        error="",
    )
    sent_messages: list[tuple[str, str]] = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def get_thread(*args, **kwargs):
        if kwargs["external_thread_id"] == approver_thread_id:
            return approver_thread
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return requester_thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"tool_approval"}\n\n'

        return stream()

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            role="assistant",
            content="",
            parts=[],
            sequence=2,
        )

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

    async def latest_pending_approval(*args, **kwargs):
        return approval

    async def send_provider_text_message(*args, **kwargs):
        sent_messages.append((kwargs["external_thread_id"], kwargs["text"]))
        return {"message_id": f"msg-{len(sent_messages)}"}

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service.repository, "get_thread", get_thread)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
    monkeypatch.setattr(service, "latest_pending_approval", latest_pending_approval)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-linked-approval-1",
            external_thread_id=requester_thread_id,
            external_user_id=requester_thread_id,
            external_user_display_name="Outside User",
            text="Restart the workload",
            raw={"messageId": "wa-inbound-linked-approval-1"},
        ),
    )

    assert processed
    assert sent_messages[0][0] == approver_thread_id
    assert "Open this Wardn approval page" in sent_messages[0][1]
    assert sent_messages[1] == (requester_thread_id, service.PROVIDER_APPROVAL_PENDING_REPLY)
    assert "Open this Wardn approval page" not in sent_messages[1][1]
    approval_events = [
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.event_type == "approval.request"
    ]
    assert len(approval_events) == 1
    assert approval_events[0].thread_id == approver_thread.id
    assert approval_events[0].status == "sent"
    assert approval_events[0].payload["approvalId"] == str(approval.id)
    assert approval_events[0].payload["externalDelivery"] is True
    assert approval_events[0].payload["routeType"] == "workspace_member"
    assert approval_events[0].payload["userId"] == str(approver_user_id)
    assert approval_events[0].payload["externalThreadId"] == approver_thread_id
    assert connection.provider in approval_events[0].payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_decision", "expected_reply"),
    [
        ("yes", "approve", service.PROVIDER_APPROVAL_APPROVED_REPLY),
        ("no", "deny", service.PROVIDER_APPROVAL_DENIED_REPLY),
    ],
)
async def test_process_provider_text_message_handles_linked_workspace_member_approval_decision(
    monkeypatch,
    text: str,
    expected_decision: str,
    expected_reply: str,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    approver_thread_id = "15557654321@s.whatsapp.net"
    approver_user_id = uuid4()
    connection.config = {
        **connection.config,
        "approval_routes": [
            {
                "route_type": "workspace_member",
                "user_id": str(approver_user_id),
                "external_thread_id": approver_thread_id,
                "display_name": "Workspace Owner",
            }
        ],
    }
    requester_conversation_id = uuid4()
    approver_conversation_id = uuid4()
    agent_id = uuid4()
    agent_run_id = uuid4()
    approval = AgentToolApproval(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_id=agent_id,
        conversation_id=requester_conversation_id,
        agent_run_id=agent_run_id,
        requested_by_id=connection.created_by_id,
        installation_id=uuid4(),
        tool_schema_id=uuid4(),
        tool_call_id="call-1",
        tool_name="restart_workload",
        arguments={"name": "api"},
        status="pending",
        result="",
        error="",
    )
    approver_thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=approver_conversation_id,
        external_thread_id=approver_thread_id,
        external_user_id=approver_thread_id,
        external_user_display_name="Workspace Owner",
    )
    approval_event = ChatProviderEvent(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        thread_id=approver_thread.id,
        conversation_id=requester_conversation_id,
        provider=connection.provider,
        external_event_id="approval-request-1",
        direction="outbound",
        event_type="approval.request",
        status="sent",
        payload={
            "agentId": str(agent_id),
            "agentRunId": str(agent_run_id),
            "approvalId": str(approval.id),
            "approvalRequest": True,
            "userId": str(approver_user_id),
        },
    )
    approver = User(id=approver_user_id, email="approver@example.com", is_active=True)
    sent_messages: list[tuple[str, str]] = []
    decisions: list[tuple[User, str, str]] = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def get_thread(*args, **kwargs):
        if kwargs["external_thread_id"] == approver_thread_id:
            return approver_thread
        return None

    async def list_sent_approval_request_events_for_thread(*args, **kwargs):
        return [approval_event]

    async def get_tool_approval(*args, **kwargs):
        assert kwargs["agent_id"] == agent_id
        assert kwargs["approval_id"] == approval.id
        return approval

    async def get_user_by_id(*args, **kwargs):
        return approver

    async def decide_agent_tool_approval(*args, **kwargs):
        decisions.append((args[1], args[6].decision, kwargs["schedule_completion"].__name__))
        approval.status = "running" if expected_decision == "approve" else "denied"
        return SimpleNamespace(approval_id=approval.id, status=approval.status)

    async def stream_agent_chat(*args, **kwargs):
        raise AssertionError("approval decisions must not start a new provider chat run")

    async def send_provider_text_message(*args, **kwargs):
        sent_messages.append((kwargs["external_thread_id"], kwargs["text"]))
        return {"message_id": "approval-decision-reply-1"}

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service.repository, "get_thread", get_thread)
    monkeypatch.setattr(
        service.repository,
        "list_sent_approval_request_events_for_thread",
        list_sent_approval_request_events_for_thread,
    )
    monkeypatch.setattr(service.agent_repository, "get_tool_approval", get_tool_approval)
    monkeypatch.setattr(service, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(
        service.agent_service,
        "decide_agent_tool_approval",
        decide_agent_tool_approval,
    )
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-approval-decision-1",
            external_thread_id=approver_thread_id,
            external_user_id=approver_thread_id,
            external_user_display_name="Workspace Owner",
            text=text,
            raw={"messageId": "wa-inbound-approval-decision-1"},
        ),
    )

    inbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "inbound"
    )
    outbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent)
        and item.event_type == "message.text"
        and item.direction == "outbound"
    )

    assert processed
    assert decisions == [(approver, expected_decision, "enqueue_agent_tool_approval_resume")]
    assert sent_messages == [(approver_thread_id, expected_reply)]
    assert inbound_event.status == "processed"
    assert inbound_event.thread_id == approver_thread.id
    assert outbound_event.status == "sent"
    assert outbound_event.payload["approvalDecision"] == expected_decision
    assert outbound_event.payload["approvalId"] == str(approval.id)
    assert outbound_event.payload["agentRunId"] == str(agent_run_id)
    assert outbound_event.payload["providerReplyKind"] == "approval_decision"


@pytest.mark.asyncio
async def test_process_provider_text_message_reports_no_pending_provider_approval(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    approver_thread_id = "15557654321@s.whatsapp.net"
    approver_user_id = uuid4()
    connection.config = {
        **connection.config,
        "approval_routes": [
            {
                "route_type": "workspace_member",
                "user_id": str(approver_user_id),
                "external_thread_id": approver_thread_id,
                "display_name": "Workspace Owner",
            }
        ],
    }
    approver_thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id=approver_thread_id,
        external_user_id=approver_thread_id,
        external_user_display_name="Workspace Owner",
    )
    sent_messages: list[tuple[str, str]] = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def get_thread(*args, **kwargs):
        return approver_thread

    async def list_sent_approval_request_events_for_thread(*args, **kwargs):
        return []

    async def decide_agent_tool_approval(*args, **kwargs):
        raise AssertionError("no pending approval should not submit a decision")

    async def stream_agent_chat(*args, **kwargs):
        raise AssertionError("approval commands in approver threads must not start chat runs")

    async def send_provider_text_message(*args, **kwargs):
        sent_messages.append((kwargs["external_thread_id"], kwargs["text"]))
        return {"message_id": "approval-no-pending-1"}

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service.repository, "get_thread", get_thread)
    monkeypatch.setattr(
        service.repository,
        "list_sent_approval_request_events_for_thread",
        list_sent_approval_request_events_for_thread,
    )
    monkeypatch.setattr(
        service.agent_service,
        "decide_agent_tool_approval",
        decide_agent_tool_approval,
    )
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-approval-no-pending-1",
            external_thread_id=approver_thread_id,
            external_user_id=approver_thread_id,
            external_user_display_name="Workspace Owner",
            text="approve",
            raw={"messageId": "wa-inbound-approval-no-pending-1"},
        ),
    )

    assert processed
    assert sent_messages == [(approver_thread_id, service.PROVIDER_APPROVAL_NO_PENDING_REPLY)]


@pytest.mark.asyncio
async def test_process_provider_text_message_never_sends_approval_to_requester_route(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    requester_thread_id = "15551234567@s.whatsapp.net"
    connection.config = {
        **connection.config,
        "approval_routes": [
            {
                "route_type": "chat_provider",
                "connection_id": str(connection.id),
                "external_thread_id": requester_thread_id,
                "display_name": "Outside User",
            }
        ],
    }
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=uuid4(),
        external_thread_id=requester_thread_id,
        external_user_id=requester_thread_id,
        external_user_display_name="Outside User",
    )
    conversation_id = thread.conversation_id
    agent_id = uuid4()
    agent_run_id = uuid4()
    approval = AgentToolApproval(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        requested_by_id=connection.created_by_id,
        installation_id=uuid4(),
        tool_schema_id=uuid4(),
        tool_call_id="call-1",
        tool_name="restart_workload",
        arguments={"name": "api"},
        status="pending",
        result="",
        error="",
    )
    sent_messages: list[tuple[str, str]] = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"tool_approval"}\n\n'

        return stream()

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            role="assistant",
            content="",
            parts=[],
            sequence=2,
        )

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

    async def latest_pending_approval(*args, **kwargs):
        return approval

    async def send_provider_text_message(*args, **kwargs):
        sent_messages.append((kwargs["external_thread_id"], kwargs["text"]))
        return {"message_id": f"msg-{len(sent_messages)}"}

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
    monkeypatch.setattr(service, "latest_pending_approval", latest_pending_approval)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-approval-requester-1",
            external_thread_id=requester_thread_id,
            external_user_id=requester_thread_id,
            external_user_display_name="Outside User",
            text="Restart the workload",
            raw={"messageId": "wa-inbound-approval-requester-1"},
        ),
    )

    assert processed
    assert sent_messages == [
        (requester_thread_id, service.PROVIDER_APPROVAL_PENDING_UNDELIVERED_REPLY)
    ]
    assert "Open this Wardn approval page" not in sent_messages[0][1]
    approval_events = [
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.event_type == "approval.request"
    ]
    assert len(approval_events) == 1
    assert approval_events[0].thread_id is None
    assert approval_events[0].status == "failed"
    assert approval_events[0].payload["externalDelivery"] is False
    assert approval_events[0].payload["routeType"] == "none"
    assert approval_events[0].payload["displayName"] == "No external approval route"


@pytest.mark.asyncio
async def test_process_provider_text_message_skips_reply_when_run_was_canceled(
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

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=uuid4(),
            role="assistant",
            content="Workspace looks healthy.",
            parts=[{"type": "text", "text": "Workspace looks healthy."}],
            sequence=2,
        )

    async def assistant_message_run_canceled(*args, **kwargs):
        return True

    async def send_provider_text_message(*args, **kwargs):
        raise AssertionError("canceled run replies must not be delivered")

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-canceled-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="What changed today?",
            raw={"messageId": "wa-inbound-canceled-1"},
        ),
    )

    outbound_events = [
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "outbound"
    ]

    assert processed
    assert outbound_events == []


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

    assistant_agent_run_id = uuid4()

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=assistant_agent_run_id,
            role="assistant",
            content="Workspace looks healthy.",
            parts=[{"type": "text", "text": "Workspace looks healthy."}],
            sequence=2,
        )

    async def send_provider_text_message(*args, **kwargs):
        return {"message_id": "wa-reply-1"}

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

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
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
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
async def test_process_provider_text_message_records_failed_assistant_reply(
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
    assistant_agent_run_id = uuid4()

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def start_provider_typing(*args, **kwargs):
        return None

    async def stream_agent_chat(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return stream()

    async def latest_assistant_message(*args, **kwargs):
        return ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            agent_run_id=assistant_agent_run_id,
            role="assistant",
            content="Workspace looks healthy.",
            parts=[{"type": "text", "text": "Workspace looks healthy."}],
            sequence=2,
        )

    async def assistant_message_run_canceled(*args, **kwargs):
        return False

    async def send_provider_text_message(*args, **kwargs):
        raise ChatProviderDeliveryError("WhatsApp local bridge delivery failed")

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service, "start_provider_typing", start_provider_typing)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "latest_assistant_message", latest_assistant_message)
    monkeypatch.setattr(service, "assistant_message_run_canceled", assistant_message_run_canceled)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-inbound-delivery-failed-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="What changed today?",
            raw={"messageId": "wa-inbound-delivery-failed-1"},
        ),
    )

    inbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "inbound"
    )
    outbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.direction == "outbound"
    )

    assert processed
    assert inbound_event.status == "processed"
    assert outbound_event.event_type == "message.text"
    assert outbound_event.status == "failed"
    assert outbound_event.error == "WhatsApp local bridge delivery failed"
    assert outbound_event.payload["agentRunId"] == str(assistant_agent_run_id)
    assert outbound_event.payload["externalThreadId"] == "15551234567@s.whatsapp.net"


@pytest.mark.asyncio
async def test_process_provider_text_message_new_command_starts_new_thread_conversation(
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
    new_conversation_id = uuid4()
    agent_id = uuid4()
    force_new_values = []
    sent_texts = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        force_new_values.append(kwargs["force_new"])
        thread.conversation_id = new_conversation_id
        return thread, new_conversation_id, agent_id

    async def stream_agent_chat(*args, **kwargs):
        raise AssertionError("/new should not call the model")

    async def send_provider_text_message(*args, **kwargs):
        sent_texts.append(kwargs["text"])
        return {"message_id": "wa-command-reply"}

    async def start_provider_typing(*args, **kwargs):
        raise AssertionError("/new should not start typing indicator")

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)
    monkeypatch.setattr(service, "start_provider_typing", start_provider_typing)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-new-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="/new",
            raw={"messageId": "wa-new-1"},
        ),
    )

    outbound_event = next(
        item
        for item in fake_session.added
        if isinstance(item, ChatProviderEvent) and item.external_event_id == "wa-command-reply"
    )

    assert processed
    assert force_new_values == [True]
    assert sent_texts == ["Started a new chat. Send your next message to begin."]
    assert outbound_event.conversation_id == new_conversation_id


@pytest.mark.asyncio
async def test_process_provider_text_message_compact_command_compacts_conversation(
    monkeypatch,
) -> None:
    fake_session = FakeSession()
    connection = make_connection()
    actor = User(id=connection.created_by_id, email="owner@example.com", is_active=True)
    conversation_id = uuid4()
    agent_id = uuid4()
    thread = ChatProviderThread(
        id=uuid4(),
        organization_id=connection.organization_id,
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        conversation_id=conversation_id,
        external_thread_id="15551234567@s.whatsapp.net",
        external_user_id="15551234567@s.whatsapp.net",
        external_user_display_name="Asha",
    )
    compact_calls = []
    sent_texts = []

    async def get_event_by_external_id(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        return actor

    async def provider_thread_conversation(*args, **kwargs):
        return thread, conversation_id, agent_id

    async def compact_workspace_conversation(*args, **kwargs):
        compact_calls.append(args)
        return SimpleNamespace(id=uuid4())

    async def stream_agent_chat(*args, **kwargs):
        raise AssertionError("/compact should not call the model")

    async def send_provider_text_message(*args, **kwargs):
        sent_texts.append(kwargs["text"])
        return {"message_id": "wa-compact-reply"}

    async def start_provider_typing(*args, **kwargs):
        raise AssertionError("/compact should not start typing indicator")

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service, "provider_actor", provider_actor)
    monkeypatch.setattr(service, "provider_thread_conversation", provider_thread_conversation)
    monkeypatch.setattr(
        service.agent_service,
        "compact_workspace_conversation",
        compact_workspace_conversation,
    )
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)
    monkeypatch.setattr(service, "send_provider_text_message", send_provider_text_message)
    monkeypatch.setattr(service, "start_provider_typing", start_provider_typing)

    processed = await service.process_provider_text_message(
        fake_session,
        connection,
        service.ProviderTextMessage(
            event_id="wa-compact-1",
            external_thread_id="15551234567@s.whatsapp.net",
            external_user_id="15551234567@s.whatsapp.net",
            external_user_display_name="Asha",
            text="/compact",
            raw={"messageId": "wa-compact-1"},
        ),
    )

    assert processed
    assert compact_calls[0][1] is actor
    assert compact_calls[0][4] == conversation_id
    assert sent_texts == [
        "Compacted this chat. Future replies will use the compacted context plus new messages."
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

    async def get_thread(*args, **kwargs):
        return None

    async def provider_actor(*args, **kwargs):
        raise AssertionError("disallowed sender must not reach the workspace agent")

    monkeypatch.setattr(service.repository, "get_event_by_external_id", get_event_by_external_id)
    monkeypatch.setattr(service.repository, "get_thread", get_thread)
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
    thread = next(item for item in fake_session.added if isinstance(item, ChatProviderThread))

    assert processed
    assert fake_session.commits == 0
    assert inbound_event.status == "ignored"
    assert inbound_event.error == "WhatsApp sender is not allowed"
    assert inbound_event.thread_id == thread.id
    assert thread.conversation_id is None
    assert thread.external_thread_id == "15551234567@s.whatsapp.net"
    assert thread.external_user_id == "15551234567@s.whatsapp.net"
    assert thread.external_user_display_name == "Asha"
    assert thread.last_external_message_id == "wa-inbound-1"


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
