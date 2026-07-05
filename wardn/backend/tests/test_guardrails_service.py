from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.agents import service as agent_service
from app.modules.agents.models import Agent, AgentRun, AgentToolApproval, WorkspaceConversation
from app.modules.agents.schemas import AgentToolApprovalDecisionRequest
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
    execution = await agent_service.execute_agent_tool_call(
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
    runtime_tool = agent_service.AgentRuntimeTool(
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
        agent_service,
        "evaluate_tool_call_guardrails",
        evaluate_tool_call_guardrails,
    )
    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(agent_service, "call_tool_with_tracking", call_tool_with_tracking)

    session = FakeSession()
    execution = await agent_service.execute_agent_tool_call(
        session,
        {"search_repositories": runtime_tool},
        agent_service.AgentToolCall(
            name="search_repositories",
            call_id="call-1",
            arguments={"query": "wardn"},
        ),
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

    monkeypatch.setattr(agent_service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(agent_service.repository, "get_agent", get_agent)
    monkeypatch.setattr(agent_service.repository, "get_tool_approval", get_tool_approval)
    monkeypatch.setattr(
        agent_service.repository,
        "list_agent_tool_runtime_rows",
        list_agent_tool_runtime_rows,
    )
    monkeypatch.setattr(agent_service, "call_tool_with_tracking", call_tool_with_tracking)
    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        agent_service.repository,
        "update_conversation_tool_activity",
        update_conversation_tool_activity,
    )
    monkeypatch.setattr(
        agent_service,
        "generate_approval_continuation_message",
        generate_approval_continuation_message,
    )
    monkeypatch.setattr(agent_service.repository, "get_agent_run", get_agent_run)
    monkeypatch.setattr(agent_service.repository, "finish_agent_run", finish_agent_run)

    response = await agent_service.decide_agent_tool_approval(
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

    monkeypatch.setattr(agent_service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(
        agent_service.repository,
        "append_conversation_message",
        append_conversation_message,
    )
    monkeypatch.setattr(agent_service.repository, "finish_agent_run", finish_agent_run)

    chunks = [
        chunk
        async for chunk in agent_service.persisted_agent_chat_stream(
            FakeSession(),
            conversation,
            stream(),
            agent_run,
        )
    ]

    assert any("requires_confirmation" in chunk for chunk in chunks)
    assert captured["run_status"] == "waiting_confirmation"
    assert captured["run_error"] == ""
