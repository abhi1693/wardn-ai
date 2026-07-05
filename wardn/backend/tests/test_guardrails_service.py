from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.agents import service as agent_service
from app.modules.agents.models import Agent, AgentRun, WorkspaceConversation
from app.modules.guardrails import repository, service
from app.modules.guardrails.exceptions import InvalidGuardrailPolicyError
from app.modules.guardrails.models import GuardrailPolicy
from app.modules.guardrails.schemas import GuardrailPolicyCreate
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        now = datetime(2026, 7, 5, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            instance.created_at = now
            instance.updated_at = now

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 7, 5, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        instance.created_at = getattr(instance, "created_at", now)
        instance.updated_at = now

    async def commit(self) -> None:
        self.commits += 1


def make_policy(mode: str, *, name: str, priority: int = 100) -> GuardrailPolicy:
    return GuardrailPolicy(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        name=name,
        description="",
        mode=mode,
        priority=priority,
        conditions={},
        is_active=True,
        created_at=datetime(2026, 7, 5, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, tzinfo=UTC),
    )


def test_guardrail_decision_prefers_deny_over_allow() -> None:
    allow = make_policy("allow", name="Allow docs", priority=1)
    deny = make_policy("deny", name="Block GitHub writes", priority=50)

    decision = service.decision_for_policies([allow, deny])

    assert decision.mode == "deny"
    assert decision.policy_id == deny.id
    assert decision.matched_policy_ids == (allow.id, deny.id)


def test_guardrail_decision_requires_confirmation_when_no_deny() -> None:
    confirm = make_policy("require_confirmation", name="Confirm prod", priority=10)

    decision = service.decision_for_policies([confirm])

    assert decision.mode == "require_confirmation"
    assert decision.policy_name == "Confirm prod"


@pytest.mark.asyncio
async def test_create_guardrail_policy_rejects_conditions(monkeypatch) -> None:
    async def require_guardrail_scope_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "require_guardrail_scope_admin", require_guardrail_scope_admin)
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    with pytest.raises(InvalidGuardrailPolicyError, match="conditions"):
        await service.create_guardrail_policy(
            FakeSession(),
            user,
            uuid4(),
            GuardrailPolicyCreate(
                name="Block writes",
                mode="deny",
                conditions={"tool": {"operation": "delete"}},
            ),
            workspace_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_workspace_tool_policy_derives_installation(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    installation_id = uuid4()
    tool_schema_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    tool_schema = MCPServerToolSchema(
        id=tool_schema_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name="io.github.example/server",
        server_version="1.0.0",
        tool_name="search",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=installation_id,
        workspace_id=workspace_id,
        server_name=tool_schema.server_name,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )

    async def require_guardrail_scope_admin(*args, **kwargs):
        return None

    async def get_policy_by_name(*args, **kwargs):
        return None

    async def get_tool_schema(*args, **kwargs):
        return tool_schema

    async def get_installation_by_id(*args, **kwargs):
        return installation

    monkeypatch.setattr(service, "require_guardrail_scope_admin", require_guardrail_scope_admin)
    monkeypatch.setattr(repository, "get_policy_by_name", get_policy_by_name)
    monkeypatch.setattr(repository, "get_tool_schema", get_tool_schema)
    monkeypatch.setattr(
        service.mcp_registry_repository,
        "get_installation_by_id",
        get_installation_by_id,
    )

    session = FakeSession()
    response = await service.create_guardrail_policy(
        session,
        user,
        organization_id,
        GuardrailPolicyCreate(
            name="Require confirmation for search",
            mode="require_confirmation",
            toolSchemaId=tool_schema_id,
        ),
        workspace_id=workspace_id,
    )

    policy = session.added[0]
    assert isinstance(policy, GuardrailPolicy)
    assert policy.workspace_id == workspace_id
    assert policy.tool_schema_id == tool_schema_id
    assert policy.installation_id == installation_id
    assert response.installation_id == installation_id


@pytest.mark.asyncio
async def test_agent_tool_call_guardrail_block_skips_runtime(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    installation_id = uuid4()
    tool_schema_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Use tools.",
        scope="workspace",
        model_name="gpt-5.5",
        is_active=True,
    )
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        title="Chat",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        triggered_by_id=user.id,
        trigger_type="chat",
        status="running",
        started_at=datetime(2026, 7, 5, tzinfo=UTC),
    )
    installation = MCPServerInstallation(
        id=installation_id,
        workspace_id=workspace_id,
        server_name="io.github.example/server",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version="1.0.0",
        description="Server",
        server_json={},
        packages=[],
        remotes=[],
        icons=[],
        is_latest=True,
        status="active",
    )
    tool_schema = MCPServerToolSchema(
        id=tool_schema_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="delete_repo",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    runtime_tool = agent_service.AgentRuntimeTool(
        wire_name="delete_repo",
        assignment_id=uuid4(),
        tool_schema=tool_schema,
        installation=installation,
        server=server,
    )
    guardrail_policy_id = uuid4()
    appended_steps = []

    async def evaluate_tool_call_guardrails(*args, **kwargs):
        return service.GuardrailDecision(
            mode="deny",
            policy_id=guardrail_policy_id,
            policy_name="Block deletes",
            message="Tool call blocked by guardrail policy: Block deletes",
            matched_policy_ids=(guardrail_policy_id,),
        )

    async def append_agent_run_step(*args, **kwargs):
        appended_steps.append(kwargs)

    async def call_tool_with_tracking(*args, **kwargs):
        raise AssertionError("runtime should not be called")

    monkeypatch.setattr(
        agent_service,
        "evaluate_tool_call_guardrails",
        evaluate_tool_call_guardrails,
    )
    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(agent_service, "call_tool_with_tracking", call_tool_with_tracking)

    session = FakeSession()
    output = await agent_service.execute_agent_tool_call(
        session,
        {"delete_repo": runtime_tool},
        agent_service.AgentToolCall(
            name="delete_repo",
            call_id="call-1",
            arguments={"repo": "prod"},
        ),
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
        conversation=conversation,
        agent_run=agent_run,
    )

    assert output.startswith(agent_service.AGENT_TOOL_BLOCKED_PREFIX)
    assert session.commits == 1
    assert appended_steps[0]["step_type"] == "guardrail_decision"
    assert appended_steps[0]["status"] == "deny"
    assert appended_steps[0]["payload"]["policyName"] == "Block deletes"
