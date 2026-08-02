from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.agents import approvals as agent_approvals
from app.modules.agents import service as agent_service
from app.modules.agents import tool_execution as agent_tool_execution
from app.modules.agents.models import Agent, AgentRun, AgentToolApproval, WorkspaceConversation
from app.modules.agents.schemas import AgentToolApprovalDecisionRequest
from app.modules.agents.types import AgentRuntimeTool
from app.modules.guardrails import repository, service
from app.modules.guardrails.exceptions import InvalidGuardrailPolicyError
from app.modules.guardrails.models import GuardrailPolicy
from app.modules.guardrails.schemas import GuardrailPolicyCreate
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.organizations.models import Workspace
from app.modules.users.models import User
from tests.database_fakes import EmptyResult


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

    async def execute(self, *args, **kwargs) -> EmptyResult:
        return EmptyResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def begin(self):
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.session.commits += 1


def fake_session_factory(session: FakeSession):
    return lambda: session


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


def test_guardrail_decision_blocks_unmatched_tool_when_allow_policy_exists() -> None:
    decision = service.decision_for_policies([], has_active_allow_policy=True)

    assert decision.mode == "deny"
    assert decision.policy_id is None
    assert "did not match any active allow guardrail policy" in decision.message
    assert decision.matched_policy_ids == ()


def test_guardrail_decision_blocks_unmatched_tool_when_workspace_default_deny() -> None:
    decision = service.decision_for_policies([], default_deny=True)

    assert decision.mode == "deny"
    assert decision.policy_id is None
    assert "workspace default-deny access mode is enabled" in decision.message
    assert decision.matched_policy_ids == ()


@pytest.mark.asyncio
async def test_get_guardrail_settings_returns_workspace_default_deny(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default",
        slug="default",
        description="",
        status="active",
        guardrail_default_deny=True,
    )

    async def require_workspace_member(*args, **kwargs):
        return workspace, None, None

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)

    response = await service.get_guardrail_settings(
        FakeSession(),
        user,
        organization_id,
        workspace_id=workspace_id,
    )

    assert response.workspace_id == workspace_id
    assert response.default_deny is True


@pytest.mark.asyncio
async def test_update_guardrail_settings_updates_workspace_default_deny(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default",
        slug="default",
        description="",
        status="active",
        guardrail_default_deny=False,
    )

    async def require_workspace_admin(*args, **kwargs):
        return workspace, None, None

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)

    response = await service.update_guardrail_settings(
        FakeSession(),
        user,
        organization_id,
        service.GuardrailSettingsUpdate(defaultDeny=True),
        workspace_id=workspace_id,
    )

    assert workspace.guardrail_default_deny is True
    assert response.workspace_id == workspace_id
    assert response.default_deny is True


@pytest.mark.asyncio
async def test_create_guardrail_policy_accepts_rule_group_conditions(monkeypatch) -> None:
    async def require_guardrail_scope_admin(*args, **kwargs):
        return None

    async def get_policy_by_name(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "require_guardrail_scope_admin", require_guardrail_scope_admin)
    monkeypatch.setattr(repository, "get_policy_by_name", get_policy_by_name)
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    conditions = {
        "operator": "all",
        "rules": [
            {"field": "tool_name", "operator": "contains", "value": "search"},
        ],
    }

    session = FakeSession()
    response = await service.create_guardrail_policy(
        session,
        user,
        uuid4(),
        GuardrailPolicyCreate(
            name="Block GitHub search",
            mode="deny",
            conditions=conditions,
        ),
        workspace_id=uuid4(),
    )

    policy = session.added[0]
    assert isinstance(policy, GuardrailPolicy)
    assert policy.conditions == conditions
    assert response.conditions == conditions


@pytest.mark.asyncio
async def test_create_guardrail_policy_rejects_invalid_rule_group(monkeypatch) -> None:
    async def require_guardrail_scope_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "require_guardrail_scope_admin", require_guardrail_scope_admin)
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    with pytest.raises(InvalidGuardrailPolicyError, match="field"):
        await service.create_guardrail_policy(
            FakeSession(),
            user,
            uuid4(),
            GuardrailPolicyCreate(
                name="Block writes",
                mode="deny",
                conditions={
                    "operator": "all",
                    "rules": [{"field": "unsupported", "operator": "equals", "value": "x"}],
                },
            ),
            workspace_id=uuid4(),
        )


def test_policy_rule_group_matches_all_expression() -> None:
    tool_schema_id = uuid4()
    context = service.GuardrailEvaluationContext(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        agent_run_id=None,
        installation_id=uuid4(),
        tool_schema_id=tool_schema_id,
        server_name="io.github.github/github-mcp-server",
        tool_name="search_repositories",
        arguments={"query": "git-rank"},
    )
    policy = make_policy("deny", name="Block GitHub search")
    policy.conditions = {
        "operator": "all",
        "rules": [
            {"field": "tool_schema_id", "operator": "equals", "value": str(tool_schema_id)},
            {"field": "tool_name", "operator": "equals", "value": "search_repositories"},
        ],
    }

    assert service.policy_matches_context(policy, context)


def test_policy_rule_group_matches_any_expression() -> None:
    context = service.GuardrailEvaluationContext(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        agent_run_id=None,
        installation_id=uuid4(),
        tool_schema_id=uuid4(),
        server_name="io.github.upstash/context7",
        tool_name="query_docs",
        arguments={},
    )
    policy = make_policy("deny", name="Block risky reads")
    policy.conditions = {
        "operator": "any",
        "rules": [
            {"field": "tool_name", "operator": "equals", "value": "delete_repo"},
            {"field": "tool_name", "operator": "equals", "value": "query_docs"},
        ],
    }

    assert service.policy_matches_context(policy, context)


def test_guardrail_policy_rejects_agent_and_server_rule_fields() -> None:
    for field in ("agent_id", "installation_id", "server_name"):
        with pytest.raises(InvalidGuardrailPolicyError, match="field"):
            service.validate_policy_conditions(
                {
                    "operator": "all",
                    "rules": [{"field": field, "operator": "equals", "value": str(uuid4())}],
                }
            )


@pytest.mark.asyncio
async def test_evaluate_guardrails_denies_unmatched_tool_when_allow_policy_exists(
    monkeypatch,
) -> None:
    allowed_tool_schema_id = uuid4()
    organization_id = uuid4()
    workspace_id = uuid4()
    allow_policy = GuardrailPolicy(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Read Only Tools",
        description="",
        mode="allow",
        priority=100,
        conditions={
            "operator": "any",
            "rules": [
                {
                    "field": "tool_schema_id",
                    "operator": "equals",
                    "value": str(allowed_tool_schema_id),
                }
            ],
        },
        is_active=True,
        created_at=datetime(2026, 7, 5, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, tzinfo=UTC),
    )

    async def list_matching_policies(*args, **kwargs):
        return [allow_policy]

    monkeypatch.setattr(repository, "list_matching_policies", list_matching_policies)

    decision = await service.evaluate_tool_call_guardrails(
        FakeSession(),
        service.GuardrailEvaluationContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            user_id=uuid4(),
            agent_id=uuid4(),
            conversation_id=None,
            agent_run_id=None,
            installation_id=uuid4(),
            tool_schema_id=uuid4(),
            server_name="io.github.AIops-tools/k8s-aiops",
            tool_name="create_namespace",
            arguments={"name": "test-ns"},
        ),
    )

    assert decision.mode == "deny"
    assert "did not match any active allow guardrail policy" in decision.message


@pytest.mark.asyncio
async def test_evaluate_guardrails_denies_unmatched_tool_when_workspace_default_deny(
    monkeypatch,
) -> None:
    async def list_matching_policies(*args, **kwargs):
        return []

    async def get_workspace_guardrail_default_deny(*args, **kwargs):
        return True

    monkeypatch.setattr(repository, "list_matching_policies", list_matching_policies)
    monkeypatch.setattr(
        repository,
        "get_workspace_guardrail_default_deny",
        get_workspace_guardrail_default_deny,
    )

    decision = await service.evaluate_tool_call_guardrails(
        FakeSession(),
        service.GuardrailEvaluationContext(
            organization_id=uuid4(),
            workspace_id=uuid4(),
            user_id=uuid4(),
            agent_id=uuid4(),
            conversation_id=None,
            agent_run_id=None,
            installation_id=uuid4(),
            tool_schema_id=uuid4(),
            server_name="io.github.AIops-tools/k8s-aiops",
            tool_name="create_namespace",
            arguments={"name": "test-ns"},
        ),
    )

    assert decision.mode == "deny"
    assert "workspace default-deny access mode is enabled" in decision.message


@pytest.mark.asyncio
async def test_create_starter_guardrail_policies_enables_default_deny_and_classifies_tools(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default",
        slug="default",
        description="",
        status="active",
        guardrail_default_deny=False,
    )
    read_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/github",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    write_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/kubernetes",
        config_name="rancher-qa",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    read_tool = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=read_installation.id,
        server_name=read_installation.server_name,
        server_version="1.0.0",
        tool_name="search_repositories",
        title="Search repositories",
        description="Search repositories",
        input_schema={"type": "object"},
        annotations={"readOnlyHint": True},
        is_active=True,
    )
    write_tool = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=write_installation.id,
        server_name=write_installation.server_name,
        server_version="1.0.0",
        tool_name="create_namespace",
        title="Create namespace",
        description="Create namespace",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )

    async def require_guardrail_scope_admin(*args, **kwargs):
        return workspace, None, None

    async def get_policy_by_name(*args, **kwargs):
        return None

    async def list_policies(*args, **kwargs):
        return []

    async def list_workspace_available_tools(*args, **kwargs):
        return [(read_tool, read_installation), (write_tool, write_installation)]

    async def count_policies(*args, **kwargs):
        return 0

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "require_guardrail_scope_admin", require_guardrail_scope_admin)
    monkeypatch.setattr(repository, "get_policy_by_name", get_policy_by_name)
    monkeypatch.setattr(repository, "list_policies", list_policies)
    monkeypatch.setattr(
        service.agents_repository,
        "list_workspace_available_tools",
        list_workspace_available_tools,
    )
    monkeypatch.setattr(repository, "count_policies_for_workspace", count_policies)
    monkeypatch.setattr(repository, "count_policies_created_by_user_for_workspace", count_policies)
    monkeypatch.setattr(service.limits_service, "lock_quota_capacity", no_op)
    monkeypatch.setattr(service.limits_service, "require_limit_available", no_op)

    response = await service.create_starter_guardrail_policies(
        FakeSession(),
        user,
        organization_id,
        service.GuardrailStarterPoliciesRequest(enable_default_deny=True),
        workspace_id=workspace_id,
    )

    assert response.default_deny is True
    assert workspace.guardrail_default_deny is True
    assert response.read_only_policy_count == 1
    assert response.confirmation_policy_count == 1
    assert [policy.mode for policy in response.created_policies] == [
        "allow",
        "require_confirmation",
    ]
    assert response.created_policies[0].conditions == service.tool_schema_condition(read_tool.id)
    assert response.created_policies[1].conditions == service.tool_schema_condition(write_tool.id)


@pytest.mark.asyncio
async def test_simulate_guardrail_policy_reports_installed_not_assigned(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    agent = Agent(
        id=agent_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Use tools.",
        scope="workspace",
        model_name="gpt-5.5",
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/github",
        config_name="github",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="search_repositories",
        title="Search repositories",
        description="Search repositories",
        input_schema={"type": "object"},
        annotations={"readOnlyHint": True},
        is_active=True,
    )

    async def require_guardrail_scope_member(*args, **kwargs):
        return None

    async def get_agent(*args, **kwargs):
        return agent

    async def list_workspace_available_tools(*args, **kwargs):
        return [(tool_schema, installation)]

    async def list_agent_tools(*args, **kwargs):
        return []

    monkeypatch.setattr(service, "require_guardrail_scope_member", require_guardrail_scope_member)
    monkeypatch.setattr(service.agents_repository, "get_agent", get_agent)
    monkeypatch.setattr(
        service.agents_repository,
        "list_workspace_available_tools",
        list_workspace_available_tools,
    )
    monkeypatch.setattr(service.agents_repository, "list_agent_tools", list_agent_tools)

    response = await service.simulate_guardrail_policy(
        FakeSession(),
        user,
        organization_id,
        service.GuardrailPolicySimulationRequest(
            agentId=agent_id,
            toolSchemaId=tool_schema.id,
            arguments={"query": "wardn"},
        ),
        workspace_id=workspace_id,
    )

    assert response.status == "installed_not_assigned"
    assert response.installed is True
    assert response.assigned is False
    assert response.allowed is False
    assert response.decision.mode == "not_evaluated"


@pytest.mark.asyncio
async def test_simulate_guardrail_policy_evaluates_assigned_tool(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    agent = Agent(
        id=agent_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace Assistant",
        instructions="Use tools.",
        scope="workspace",
        model_name="gpt-5.5",
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/kubernetes",
        config_name="rancher-qa",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="create_namespace",
        title="Create namespace",
        description="Create namespace",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    policy = GuardrailPolicy(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Confirm Kubernetes changes",
        description="",
        mode="require_confirmation",
        priority=50,
        conditions=service.tool_schema_condition(tool_schema.id),
        is_active=True,
        created_at=datetime(2026, 7, 5, tzinfo=UTC),
        updated_at=datetime(2026, 7, 5, tzinfo=UTC),
    )

    async def require_guardrail_scope_member(*args, **kwargs):
        return None

    async def get_agent(*args, **kwargs):
        return agent

    async def list_workspace_available_tools(*args, **kwargs):
        return [(tool_schema, installation)]

    async def list_agent_tools(*args, **kwargs):
        return [(SimpleNamespace(id=uuid4()), tool_schema, installation)]

    async def list_matching_policies(*args, **kwargs):
        return [policy]

    async def get_workspace_guardrail_default_deny(*args, **kwargs):
        return True

    monkeypatch.setattr(service, "require_guardrail_scope_member", require_guardrail_scope_member)
    monkeypatch.setattr(service.agents_repository, "get_agent", get_agent)
    monkeypatch.setattr(
        service.agents_repository,
        "list_workspace_available_tools",
        list_workspace_available_tools,
    )
    monkeypatch.setattr(service.agents_repository, "list_agent_tools", list_agent_tools)
    monkeypatch.setattr(repository, "list_matching_policies", list_matching_policies)
    monkeypatch.setattr(
        repository,
        "get_workspace_guardrail_default_deny",
        get_workspace_guardrail_default_deny,
    )

    response = await service.simulate_guardrail_policy(
        FakeSession(),
        user,
        organization_id,
        service.GuardrailPolicySimulationRequest(
            agentId=agent_id,
            toolSchemaId=tool_schema.id,
            arguments={"name": "test-ns"},
        ),
        workspace_id=workspace_id,
    )

    assert response.status == "requires_confirmation"
    assert response.assigned is True
    assert response.allowed is False
    assert response.requires_confirmation is True
    assert response.blocked is False
    assert response.decision.policy_id == policy.id
    assert response.decision.policy_name == "Confirm Kubernetes changes"


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
    runtime_tool = AgentRuntimeTool(
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
        agent_tool_execution,
        "evaluate_tool_call_guardrails",
        evaluate_tool_call_guardrails,
    )
    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        agent_tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    session = FakeSession()
    execution = await agent_service.execute_agent_tool_call(
        {"delete_repo": runtime_tool},
        agent_service.AgentToolCall(
            name="delete_repo",
            call_id="call-1",
            arguments={"repo": "prod"},
        ),
        session_factory=fake_session_factory(session),
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
        conversation=conversation,
        agent_run=agent_run,
    )

    assert execution.output.startswith(agent_service.AGENT_TOOL_BLOCKED_PREFIX)
    assert execution.status == "blocked"
    assert session.commits == 1
    assert appended_steps[0]["step_type"] == "guardrail_decision"
    assert appended_steps[0]["status"] == "deny"
    assert appended_steps[0]["payload"]["policyName"] == "Block deletes"


@pytest.mark.asyncio
async def test_agent_tool_call_guardrail_confirmation_creates_approval(monkeypatch) -> None:
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
        tool_name="search_repositories",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    runtime_tool = AgentRuntimeTool(
        wire_name="search_repositories",
        assignment_id=uuid4(),
        tool_schema=tool_schema,
        installation=installation,
        server=server,
    )

    async def evaluate_tool_call_guardrails(*args, **kwargs):
        return service.GuardrailDecision(
            mode="require_confirmation",
            policy_id=uuid4(),
            policy_name="Confirm searches",
            message="Tool call requires confirmation",
            matched_policy_ids=(uuid4(),),
        )

    async def append_agent_run_step(*args, **kwargs):
        return None

    async def call_tool_with_tracking(*args, **kwargs):
        raise AssertionError("runtime should not be called before approval")

    monkeypatch.setattr(
        agent_tool_execution,
        "evaluate_tool_call_guardrails",
        evaluate_tool_call_guardrails,
    )
    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        agent_tool_execution,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    session = FakeSession()
    execution = await agent_service.execute_agent_tool_call(
        {"search_repositories": runtime_tool},
        agent_service.AgentToolCall(
            name="search_repositories",
            call_id="call-1",
            arguments={"query": "wardn"},
        ),
        session_factory=fake_session_factory(session),
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
        conversation=conversation,
        agent_run=agent_run,
    )

    approvals = [entry for entry in session.added if isinstance(entry, AgentToolApproval)]
    assert execution.status == "requires_confirmation"
    assert execution.approval
    assert execution.approval["id"] == str(approvals[0].id)
    review = execution.approval["actionReview"]
    assert review["targetConnection"] == {
        "serverName": "io.github.example/server",
        "serverVersion": "1.0.0",
        "installationId": str(installation_id),
        "configurationName": "default",
        "installType": "",
    }
    assert review["targetEnvironment"] == {
        "configuredTarget": "default",
        "provider": None,
        "runtimeKind": None,
    }
    assert review["tool"]["name"] == "search_repositories"
    assert review["normalizedArguments"] == {"query": "wardn"}
    assert review["matchingPolicy"]["mode"] == "require_confirmation"
    assert review["matchingPolicy"]["policyName"] == "Confirm searches"
    assert approvals[0].arguments == {"query": "wardn"}
    assert approvals[0].requested_by_id == user.id
    assert session.commits == 1


@pytest.mark.asyncio
async def test_approve_agent_tool_approval_executes_stored_tool_call(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
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
    installation = MCPServerInstallation(
        id=uuid4(),
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
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="search_repositories",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    approval = AgentToolApproval(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        requested_by_id=user.id,
        installation_id=installation.id,
        tool_schema_id=tool_schema.id,
        tool_call_id="call-1",
        tool_name=tool_schema.tool_name,
        arguments={"query": "wardn"},
        status="pending",
        result="",
        error="",
    )
    captured: dict[str, object] = {}

    async def require_workspace_member(*args, **kwargs):
        return None

    async def get_agent(*args, **kwargs):
        return agent

    async def get_tool_approval(*args, **kwargs):
        return approval

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        return [(SimpleNamespace(id=uuid4()), tool_schema, installation, server)]

    async def call_tool_with_tracking(*args, **kwargs):
        captured["arguments"] = kwargs["arguments"]
        return {"content": [{"type": "text", "text": "done"}]}

    async def append_agent_run_step(*args, **kwargs):
        captured["step_status"] = kwargs["status"]

    async def update_conversation_tool_activity(*args, **kwargs):
        captured["activity_update"] = kwargs["data_update"]
        return True

    async def generate_approval_continuation_message(*args, **kwargs):
        return None

    async def get_agent_run(*args, **kwargs):
        return AgentRun(
            id=approval.agent_run_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent.id,
            conversation_id=approval.conversation_id,
            triggered_by_id=user.id,
            trigger_type="chat",
            status="waiting_confirmation",
            started_at=datetime(2026, 7, 5, tzinfo=UTC),
        )

    async def finish_agent_run(*args, **kwargs):
        captured["run_status"] = kwargs["status"]
        return args[1]

    monkeypatch.setattr(agent_approvals, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(agent_service.repository, "get_agent", get_agent)
    monkeypatch.setattr(agent_service.repository, "get_tool_approval", get_tool_approval)
    monkeypatch.setattr(
        agent_service.repository,
        "list_agent_tool_runtime_rows",
        list_agent_tool_runtime_rows,
    )
    monkeypatch.setattr(
        agent_approvals,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )
    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        agent_service.repository,
        "update_conversation_tool_activity",
        update_conversation_tool_activity,
    )
    monkeypatch.setattr(
        agent_approvals,
        "generate_approval_continuation_message",
        generate_approval_continuation_message,
    )
    monkeypatch.setattr(agent_service.repository, "get_agent_run", get_agent_run)
    monkeypatch.setattr(agent_service.repository, "finish_agent_run", finish_agent_run)

    response = await agent_approvals.decide_agent_tool_approval(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
        agent.id,
        approval.id,
        AgentToolApprovalDecisionRequest(decision="approve"),
    )

    assert captured["arguments"] == {"query": "wardn"}
    assert captured["step_status"] == "completed"
    assert captured["activity_update"] == {"status": "completed", "result": "done"}
    assert captured["run_status"] == "succeeded"
    assert approval.status == "completed"
    assert response.status == "completed"
    assert response.result == "done"


@pytest.mark.asyncio
async def test_persisted_chat_stream_leaves_confirmation_run_waiting(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        title="Chat",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        conversation_id=conversation.id,
        triggered_by_id=uuid4(),
        trigger_type="chat",
        status="running",
        started_at=datetime(2026, 7, 5, tzinfo=UTC),
    )
    captured: dict[str, object] = {}

    async def stream():
        yield agent_service.AgentChatToolActivityEvent(
            id="tool-call-1",
            tool_name="search_repositories",
            status="requires_confirmation",
            error="Tool requires confirmation: Confirm searches",
            approval={"id": str(uuid4()), "status": "pending"},
        )

    async def append_agent_run_step(*args, **kwargs):
        return None

    async def append_conversation_message(*args, **kwargs):
        captured["message_parts"] = kwargs["parts"]
        return None

    async def finish_agent_run(*args, **kwargs):
        captured["run_status"] = kwargs["status"]
        captured["run_error"] = kwargs["error"]
        return agent_run

    async def get_agent_run(*args, **kwargs):
        return agent_run

    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        agent_service.repository,
        "append_conversation_message",
        append_conversation_message,
    )
    monkeypatch.setattr(agent_service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(agent_service.repository, "get_agent_run", get_agent_run)

    session = FakeSession()
    chunks = [
        chunk
        async for chunk in agent_service.persisted_agent_chat_stream(
            conversation,
            stream(),
            agent_run,
            session_factory=fake_session_factory(session),
        )
    ]

    assert any("requires_confirmation" in chunk for chunk in chunks)
    assert captured["run_status"] == "waiting_confirmation"
    assert captured["run_error"] == ""
