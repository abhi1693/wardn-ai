import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository as agents_repository
from app.modules.guardrails import repository
from app.modules.guardrails.exceptions import (
    DuplicateGuardrailPolicyError,
    GuardrailPolicyNotFoundError,
    InvalidGuardrailPolicyError,
)
from app.modules.guardrails.models import GuardrailPolicy
from app.modules.guardrails.schemas import (
    GuardrailPolicyCreate,
    GuardrailPolicyListResponse,
    GuardrailPolicyRead,
    GuardrailPolicyUpdate,
)
from app.modules.mcp_registry import repository as mcp_registry_repository
from app.modules.organizations.service import (
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.models import User

GuardrailMode = Literal["allow", "deny", "require_confirmation"]
GUARDRAIL_MODE_ALLOW = "allow"
GUARDRAIL_MODE_DENY = "deny"
GUARDRAIL_MODE_REQUIRE_CONFIRMATION = "require_confirmation"


@dataclass(frozen=True)
class GuardrailEvaluationContext:
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    installation_id: uuid.UUID
    tool_schema_id: uuid.UUID | None
    server_name: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class GuardrailDecision:
    mode: GuardrailMode
    policy_id: uuid.UUID | None = None
    policy_name: str = ""
    message: str = ""
    matched_policy_ids: tuple[uuid.UUID, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.mode == GUARDRAIL_MODE_ALLOW


@dataclass(frozen=True)
class PolicyTargets:
    agent_id: uuid.UUID | None
    installation_id: uuid.UUID | None
    tool_schema_id: uuid.UUID | None


def policy_response(policy: GuardrailPolicy) -> GuardrailPolicyRead:
    return GuardrailPolicyRead(
        id=policy.id,
        organizationId=policy.organization_id,
        workspaceId=policy.workspace_id,
        agentId=policy.agent_id,
        installationId=policy.installation_id,
        toolSchemaId=policy.tool_schema_id,
        createdById=policy.created_by_id,
        name=policy.name,
        description=policy.description,
        mode=policy.mode,
        priority=policy.priority,
        conditions=policy.conditions,
        isActive=policy.is_active,
        createdAt=policy.created_at,
        updatedAt=policy.updated_at,
    )


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


async def require_guardrail_scope_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    await require_workspace_member(session, user, organization_id, workspace_id)


async def require_guardrail_scope_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    await require_workspace_admin(session, user, organization_id, workspace_id)


def ensure_conditions_not_enabled(conditions: dict[str, Any]) -> None:
    if conditions:
        raise InvalidGuardrailPolicyError("policy conditions are not supported yet")


async def validate_policy_targets(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    installation_id: uuid.UUID | None,
    tool_schema_id: uuid.UUID | None,
) -> PolicyTargets:
    if agent_id is not None:
        agent = await agents_repository.get_agent(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            include_inactive=True,
        )
        if agent is None:
            raise InvalidGuardrailPolicyError("agent is not available in this organization")
        if agent.workspace_id != workspace_id:
            raise InvalidGuardrailPolicyError("agent does not belong to this workspace")

    installation = None
    if installation_id is not None:
        installation = await mcp_registry_repository.get_installation_by_id(
            session,
            installation_id,
            workspace_id=workspace_id,
        )
        if installation is None:
            raise InvalidGuardrailPolicyError("MCP server is not installed in this workspace")

    if tool_schema_id is not None:
        tool_schema = await repository.get_tool_schema(
            session,
            tool_schema_id=tool_schema_id,
            workspace_id=workspace_id,
        )
        if tool_schema is None:
            raise InvalidGuardrailPolicyError("MCP tool is not available in this workspace")
        if installation_id is not None and tool_schema.installation_id != installation_id:
            raise InvalidGuardrailPolicyError("MCP tool does not belong to the selected server")
        if installation_id is None:
            installation_id = tool_schema.installation_id
        if installation_id is not None and installation is None:
            installation = await mcp_registry_repository.get_installation_by_id(
                session,
                installation_id,
                workspace_id=workspace_id,
            )
            if installation is None:
                raise InvalidGuardrailPolicyError("MCP server is not installed in this workspace")

    return PolicyTargets(
        agent_id=agent_id,
        installation_id=installation_id,
        tool_schema_id=tool_schema_id,
    )


async def ensure_unique_policy_name(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    name: str,
    existing_policy_id: uuid.UUID | None = None,
) -> None:
    existing = await repository.get_policy_by_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=name,
    )
    if existing is not None and existing.id != existing_policy_id:
        raise DuplicateGuardrailPolicyError("guardrail policy name already exists")


async def list_guardrail_policies(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailPolicyListResponse:
    await require_guardrail_scope_member(session, user, organization_id, workspace_id)
    policies = await repository.list_policies(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return GuardrailPolicyListResponse(policies=[policy_response(policy) for policy in policies])


async def get_guardrail_policy(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    policy_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailPolicyRead:
    await require_guardrail_scope_member(session, user, organization_id, workspace_id)
    policy = await repository.get_policy(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        policy_id=policy_id,
    )
    if policy is None:
        raise GuardrailPolicyNotFoundError("guardrail policy not found")
    return policy_response(policy)


async def create_guardrail_policy(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: GuardrailPolicyCreate,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailPolicyRead:
    await require_guardrail_scope_admin(session, user, organization_id, workspace_id)
    ensure_conditions_not_enabled(payload.conditions)
    name = normalize_name(payload.name)
    await ensure_unique_policy_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=name,
    )
    targets = await validate_policy_targets(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=payload.agent_id,
        installation_id=payload.installation_id,
        tool_schema_id=payload.tool_schema_id,
    )
    policy = GuardrailPolicy(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=targets.agent_id,
        installation_id=targets.installation_id,
        tool_schema_id=targets.tool_schema_id,
        created_by_id=user.id,
        name=name,
        description=payload.description,
        mode=payload.mode,
        priority=payload.priority,
        conditions=payload.conditions,
        is_active=payload.is_active,
    )
    session.add(policy)
    await session.flush()
    await session.refresh(policy)
    return policy_response(policy)


async def update_guardrail_policy(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    policy_id: uuid.UUID,
    payload: GuardrailPolicyUpdate,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailPolicyRead:
    await require_guardrail_scope_admin(session, user, organization_id, workspace_id)
    policy = await repository.get_policy(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        policy_id=policy_id,
    )
    if policy is None:
        raise GuardrailPolicyNotFoundError("guardrail policy not found")

    update_fields = payload.model_fields_set
    name = normalize_name(payload.name) if "name" in update_fields and payload.name else policy.name
    conditions = payload.conditions if "conditions" in update_fields else policy.conditions
    ensure_conditions_not_enabled(conditions or {})
    await ensure_unique_policy_name(
        session,
        organization_id=organization_id,
        workspace_id=policy.workspace_id,
        name=name,
        existing_policy_id=policy.id,
    )
    targets = await validate_policy_targets(
        session,
        organization_id=organization_id,
        workspace_id=policy.workspace_id,
        agent_id=payload.agent_id if "agent_id" in update_fields else policy.agent_id,
        installation_id=(
            payload.installation_id
            if "installation_id" in update_fields
            else policy.installation_id
        ),
        tool_schema_id=(
            payload.tool_schema_id if "tool_schema_id" in update_fields else policy.tool_schema_id
        ),
    )

    policy.name = name
    if "description" in update_fields and payload.description is not None:
        policy.description = payload.description
    if "mode" in update_fields and payload.mode is not None:
        policy.mode = payload.mode
    if "priority" in update_fields and payload.priority is not None:
        policy.priority = payload.priority
    if "conditions" in update_fields:
        policy.conditions = conditions or {}
    if "is_active" in update_fields and payload.is_active is not None:
        policy.is_active = payload.is_active
    if {"agent_id", "installation_id", "tool_schema_id"} & update_fields:
        policy.agent_id = targets.agent_id
        policy.installation_id = targets.installation_id
        policy.tool_schema_id = targets.tool_schema_id

    await session.flush()
    await session.refresh(policy)
    return policy_response(policy)


async def delete_guardrail_policy(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    policy_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID,
) -> None:
    await require_guardrail_scope_admin(session, user, organization_id, workspace_id)
    policy = await repository.get_policy(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        policy_id=policy_id,
    )
    if policy is None:
        raise GuardrailPolicyNotFoundError("guardrail policy not found")
    await repository.delete_policy(session, policy)


def decision_for_policies(policies: list[GuardrailPolicy]) -> GuardrailDecision:
    matched_policy_ids = tuple(policy.id for policy in policies)
    for mode in (GUARDRAIL_MODE_DENY, GUARDRAIL_MODE_REQUIRE_CONFIRMATION):
        policy = next((item for item in policies if item.mode == mode), None)
        if policy is None:
            continue
        message = (
            f"Tool call blocked by guardrail policy: {policy.name}"
            if mode == GUARDRAIL_MODE_DENY
            else f"Tool call requires confirmation by guardrail policy: {policy.name}"
        )
        return GuardrailDecision(
            mode=mode,
            policy_id=policy.id,
            policy_name=policy.name,
            message=message,
            matched_policy_ids=matched_policy_ids,
        )
    allow_policy = next((item for item in policies if item.mode == GUARDRAIL_MODE_ALLOW), None)
    if allow_policy is not None:
        return GuardrailDecision(
            mode=GUARDRAIL_MODE_ALLOW,
            policy_id=allow_policy.id,
            policy_name=allow_policy.name,
            message=f"Tool call allowed by guardrail policy: {allow_policy.name}",
            matched_policy_ids=matched_policy_ids,
        )
    return GuardrailDecision(
        mode=GUARDRAIL_MODE_ALLOW,
        message="No guardrail policy matched.",
        matched_policy_ids=matched_policy_ids,
    )


async def evaluate_tool_call_guardrails(
    session: AsyncSession,
    context: GuardrailEvaluationContext,
) -> GuardrailDecision:
    policies = await repository.list_matching_policies(
        session,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        installation_id=context.installation_id,
        tool_schema_id=context.tool_schema_id,
    )
    return decision_for_policies(policies)
