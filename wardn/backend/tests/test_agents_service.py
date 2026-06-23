from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.agents import service
from app.modules.agents.exceptions import (
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.models import Agent, AgentTool
from app.modules.agents.schemas import AgentChatMessage, AgentCreate, AgentToolAssignmentUpdate
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerToolSchema
from app.modules.organizations.models import Organization, OrganizationMembership, Workspace
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            instance.created_at = now
            instance.updated_at = now

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        instance.created_at = getattr(instance, "created_at", now)
        instance.updated_at = now


def test_provider_messages_keeps_text_user_and_assistant_messages() -> None:
    messages = [
        AgentChatMessage(role="system", parts=[{"type": "text", "text": "ignored"}]),
        AgentChatMessage(
            role="user",
            parts=[
                {"type": "text", "text": "hello"},
                {"type": "file", "text": "ignored"},
                {"type": "text", "text": "world"},
            ],
        ),
        AgentChatMessage(role="assistant", parts=[{"type": "text", "text": "answer"}]),
        AgentChatMessage(role="user", parts=[{"type": "text", "text": ""}]),
    ]

    assert service.provider_messages(messages) == [
        {"role": "user", "content": "hello\nworld"},
        {"role": "assistant", "content": "answer"},
    ]


def test_sse_payloads_parses_complete_json_blocks_and_preserves_tail() -> None:
    payloads, tail = service.sse_payloads(
        'event: message\ndata: {"type":"response.output_text.delta","delta":"hi"}\n\n'
        "data: [DONE]\n\n"
        'data: {"partial":'
    )

    assert payloads == [{"type": "response.output_text.delta", "delta": "hi"}]
    assert tail == 'data: {"partial":'


def test_text_delta_from_openai_event_supports_responses_and_chat_chunks() -> None:
    assert (
        service.text_delta_from_openai_event(
            {"type": "response.output_text.delta", "delta": "hello"}
        )
        == "hello"
    )
    assert (
        service.text_delta_from_openai_event({"choices": [{"delta": {"content": "world"}}]})
        == "world"
    )


def test_chatgpt_codex_request_body_uses_websocket_response_create_shape() -> None:
    agent = Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="SRE Agent",
        instructions="Use tools carefully.",
        scope="organization",
        model_name="gpt-5.3-codex-spark",
    )

    body = service.chatgpt_codex_request_body(
        agent,
        input_items=service.chatgpt_codex_messages(
            [AgentChatMessage(role="user", parts=[{"type": "text", "text": "hello"}])]
        ),
        tools=[],
    )

    assert body == {
        "type": "response.create",
        "model": "gpt-5.3-codex-spark",
        "instructions": "Use tools carefully.",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }
        ],
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": None,
        "store": False,
        "stream": True,
        "include": [],
    }


def test_tool_calls_from_response_output_item_done() -> None:
    calls = service.tool_calls_from_event(
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": "wardn_abc",
                "call_id": "call_123",
                "arguments": '{"namespace":"media"}',
            },
        }
    )

    assert calls == [
        service.AgentToolCall(
            name="wardn_abc",
            call_id="call_123",
            arguments={"namespace": "media"},
        )
    ]


def test_websocket_error_message_reads_codex_error_events() -> None:
    assert (
        service.websocket_error_message(
            {
                "type": "error",
                "status": 400,
                "error": {"message": "Model does not support this request"},
            }
        )
        == "Model does not support this request"
    )


def test_codex_compat_headers_use_current_default_version() -> None:
    assert service.CODEX_COMPAT_VERSION == service.DEFAULT_CODEX_COMPAT_VERSION
    assert service.CODEX_COMPAT_VERSION == "0.142.0"
    assert service.CODEX_COMPAT_USER_AGENT.startswith("codex_cli_rs/0.142.0 ")


def patch_org_owner(monkeypatch, organization_id, user):
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    org_repository = service.require_organization_admin.__globals__["repository"]
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)


@pytest.mark.asyncio
async def test_get_agent_model_for_run_allows_workspace_member(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="OpenAI",
        provider="openai",
        visibility="workspace",
        secret_value="sk-test",
        base_url="",
        extra_headers={},
        is_default=False,
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        provider_credential_id=credential.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        model_name="gpt-4o-mini",
        is_active=True,
    )
    calls: list[str] = []

    async def require_organization_member(*args, **kwargs):
        calls.append("organization_member")
        return None, None

    async def require_workspace_member(*args, **kwargs):
        calls.append("workspace_member")
        return None, None, None

    async def require_workspace_admin(*args, **kwargs):
        raise AssertionError("running an agent should not require workspace admin access")

    async def get_agent(*args, **kwargs):
        return agent

    async def get_credential(*args, **kwargs):
        return credential

    monkeypatch.setattr(service, "require_organization_member", require_organization_member)
    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)

    result_agent, result_credential = await service.get_agent_model_for_run(
        FakeSession(),
        user,
        organization_id,
        agent.id,
    )

    assert result_agent is agent
    assert result_credential is credential
    assert calls == ["organization_member", "workspace_member"]


@pytest.mark.asyncio
async def test_create_agent_with_provider_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        secret_value="sk-test",
        base_url="",
        extra_headers={},
        is_default=True,
        is_active=True,
    )

    patch_org_owner(monkeypatch, organization_id, user)

    async def no_duplicate(*args, **kwargs):
        return None

    async def get_credential(*args, **kwargs):
        return credential

    async def credential_supports_model(*args, **kwargs):
        return True

    monkeypatch.setattr(service.repository, "get_agent_by_name", no_duplicate)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "credential_supports_model", credential_supports_model)

    session = FakeSession()
    response = await service.create_agent(
        session,
        user,
        organization_id,
        AgentCreate(
            name=" SRE Agent ",
            description=" Runtime helper ",
            instructions="Use tools carefully.",
            providerCredentialId=credential.id,
            modelName="gpt-4o-mini",
        ),
    )

    agent = session.added[0]
    assert isinstance(agent, Agent)
    assert agent.name == "SRE Agent"
    assert agent.provider_credential_id == credential.id
    assert agent.scope == "organization"
    assert response.tool_count == 0


@pytest.mark.asyncio
async def test_create_agent_rejects_model_unavailable_for_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        secret_value="sk-test",
        base_url="",
        extra_headers={},
        is_default=True,
        is_active=True,
    )

    patch_org_owner(monkeypatch, organization_id, user)

    async def no_duplicate(*args, **kwargs):
        return None

    async def get_credential(*args, **kwargs):
        return credential

    async def credential_supports_model(*args, **kwargs):
        return False

    monkeypatch.setattr(service.repository, "get_agent_by_name", no_duplicate)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "credential_supports_model", credential_supports_model)

    session = FakeSession()
    with pytest.raises(InvalidAgentScopeError):
        await service.create_agent(
            session,
            user,
            organization_id,
            AgentCreate(
                name="SRE Agent",
                instructions="Use tools carefully.",
                providerCredentialId=credential.id,
                modelName="not-a-real-model",
            ),
        )

    assert session.added == []


@pytest.mark.asyncio
async def test_create_agent_rejects_duplicate_name(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    patch_org_owner(monkeypatch, organization_id, user)

    async def duplicate(*args, **kwargs):
        return Agent(
            id=uuid4(),
            organization_id=organization_id,
            name="SRE Agent",
            instructions="Existing",
            scope="organization",
        )

    monkeypatch.setattr(service.repository, "get_agent_by_name", duplicate)

    with pytest.raises(DuplicateAgentError):
        await service.create_agent(
            FakeSession(),
            user,
            organization_id,
            AgentCreate(name="SRE Agent", instructions="Use tools carefully."),
        )


@pytest.mark.asyncio
async def test_replace_agent_tools_rejects_tool_outside_workspace(monkeypatch) -> None:
    organization_id = uuid4()
    agent_workspace_id = uuid4()
    other_workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=agent_workspace_id,
        created_by_id=user.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        is_active=True,
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=other_workspace_id,
        installation_id=uuid4(),
        server_name="io.github.example/server",
        server_version="1.0.0",
        tool_name="list_things",
        title="List things",
        description="",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=tool_schema.installation_id,
        workspace_id=other_workspace_id,
        server_name=tool_schema.server_name,
        installed_version="1.0.0",
        status="enabled",
    )
    workspace = Workspace(
        id=other_workspace_id,
        organization_id=organization_id,
        name="Other",
        slug="other",
        status="active",
    )

    async def get_agent(*args, **kwargs):
        return agent

    async def get_tool_schemas_by_ids(*args, **kwargs):
        return [(tool_schema, installation, workspace)]

    async def require_workspace_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.repository, "get_tool_schemas_by_ids", get_tool_schemas_by_ids)
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)

    with pytest.raises(InvalidAgentToolAssignmentError):
        await service.replace_agent_tools(
            FakeSession(),
            user,
            organization_id,
            agent.id,
            AgentToolAssignmentUpdate(toolSchemaIds=[tool_schema.id]),
        )


@pytest.mark.asyncio
async def test_replace_agent_tools_persists_unique_assignments(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        is_active=True,
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=uuid4(),
        server_name="io.github.example/server",
        server_version="1.0.0",
        tool_name="list_things",
        title="List things",
        description="",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=tool_schema.installation_id,
        workspace_id=workspace_id,
        server_name=tool_schema.server_name,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )

    async def get_agent(*args, **kwargs):
        return agent

    async def get_tool_schemas_by_ids(*args, **kwargs):
        return [(tool_schema, installation, workspace)]

    async def replace_agent_tools(*args, **kwargs):
        return None

    async def list_agent_tools(*args, **kwargs):
        assignment = AgentTool(
            id=uuid4(),
            agent_id=agent.id,
            tool_schema_id=tool_schema.id,
            installation_id=installation.id,
            created_at=datetime(2026, 6, 23, tzinfo=UTC),
        )
        return [(assignment, tool_schema, installation)]

    async def require_workspace_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.repository, "get_tool_schemas_by_ids", get_tool_schemas_by_ids)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "list_agent_tools", list_agent_tools)
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)

    response = await service.replace_agent_tools(
        FakeSession(),
        user,
        organization_id,
        agent.id,
        AgentToolAssignmentUpdate(toolSchemaIds=[tool_schema.id, tool_schema.id]),
    )

    assert len(response.tools) == 1
    assert response.tools[0].tool_schema_id == tool_schema.id
    assert response.tools[0].installation_id == installation.id
