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
from app.modules.agents.schemas import AgentCreate, AgentToolAssignmentUpdate
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
