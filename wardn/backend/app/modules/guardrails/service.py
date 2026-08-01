import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
from app.modules.agents import repository as agents_repository
from app.modules.agents.exceptions import AgentNotFoundError
from app.modules.guardrails import repository
from app.modules.guardrails.exceptions import (
    DuplicateGuardrailPolicyError,
    GuardrailPolicyNotFoundError,
    InvalidGuardrailPolicyError,
)
from app.modules.guardrails.models import GuardrailPolicy
from app.modules.guardrails.schemas import (
    GuardrailDecisionRead,
    GuardrailPolicyCreate,
    GuardrailPolicyListResponse,
    GuardrailPolicyRead,
    GuardrailPolicySimulationRequest,
    GuardrailPolicySimulationResponse,
    GuardrailPolicyUpdate,
    GuardrailSettingsRead,
    GuardrailSettingsUpdate,
    GuardrailStarterPoliciesRequest,
    GuardrailStarterPoliciesResponse,
)
from app.modules.limits import service as limits_service
from app.modules.organizations.models import (
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from app.modules.organizations.service import (
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.models import User

GuardrailMode = Literal["allow", "deny", "require_confirmation"]
GUARDRAIL_MODE_ALLOW = "allow"
GUARDRAIL_MODE_DENY = "deny"
GUARDRAIL_MODE_REQUIRE_CONFIRMATION = "require_confirmation"
RULE_GROUP_OPERATORS = {"all", "any"}
RULE_OPERATORS = {"equals", "not_equals", "contains", "in"}
RULE_FIELDS = {"tool_schema_id", "tool_name"}
MAX_POLICY_RULE_DEPTH = 3
MAX_POLICY_RULES = 50
STARTER_POLICY_NAME_MAX_LENGTH = 120
SIMULATION_STATUS_ALLOWED = "allowed"
SIMULATION_STATUS_REQUIRES_CONFIRMATION = "requires_confirmation"
SIMULATION_STATUS_BLOCKED_BY_POLICY = "blocked_by_policy"
SIMULATION_STATUS_INSTALLED_NOT_ASSIGNED = "installed_not_assigned"
SIMULATION_STATUS_TOOL_NOT_INSTALLED = "tool_not_installed"


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


def policy_response(policy: GuardrailPolicy) -> GuardrailPolicyRead:
    return GuardrailPolicyRead(
        id=policy.id,
        organizationId=policy.organization_id,
        workspaceId=policy.workspace_id,
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


def decision_response(decision: GuardrailDecision) -> GuardrailDecisionRead:
    return GuardrailDecisionRead(
        mode=decision.mode,
        policyId=decision.policy_id,
        policyName=decision.policy_name,
        message=decision.message,
        matchedPolicyIds=list(decision.matched_policy_ids),
    )


def not_evaluated_decision_response(message: str) -> GuardrailDecisionRead:
    return GuardrailDecisionRead(
        mode="not_evaluated",
        message=message,
    )


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


async def require_guardrail_scope_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[Workspace, OrganizationMembership | None, WorkspaceMembership | None]:
    return await require_workspace_member(session, user, organization_id, workspace_id)


async def require_guardrail_scope_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[Workspace, OrganizationMembership | None, WorkspaceMembership | None]:
    return await require_workspace_admin(session, user, organization_id, workspace_id)


def guardrail_context_value(context: GuardrailEvaluationContext, field: str) -> Any:
    if field == "tool_schema_id":
        return str(context.tool_schema_id) if context.tool_schema_id else None
    if field == "tool_name":
        return context.tool_name
    return None


def normalize_rule_value(value: Any) -> str:
    return str(value).strip()


def values_equal(left: Any, right: Any) -> bool:
    if left is None:
        return right is None
    return str(left) == normalize_rule_value(right)


def validate_rule_node(node: Any, *, depth: int = 0) -> int:
    if not isinstance(node, dict):
        raise InvalidGuardrailPolicyError("guardrail policy rule must be an object")
    if depth > MAX_POLICY_RULE_DEPTH:
        raise InvalidGuardrailPolicyError("guardrail policy rule nesting is too deep")
    if "rules" in node:
        operator = node.get("operator")
        if operator not in RULE_GROUP_OPERATORS:
            raise InvalidGuardrailPolicyError("guardrail policy group operator must be all or any")
        rules = node.get("rules")
        if not isinstance(rules, list):
            raise InvalidGuardrailPolicyError("guardrail policy group rules must be a list")
        if len(rules) > MAX_POLICY_RULES:
            raise InvalidGuardrailPolicyError("guardrail policy has too many rules")
        return sum(validate_rule_node(rule, depth=depth + 1) for rule in rules)

    field = node.get("field")
    operator = node.get("operator", "equals")
    if field not in RULE_FIELDS:
        raise InvalidGuardrailPolicyError("guardrail policy rule field is not supported")
    if operator not in RULE_OPERATORS:
        raise InvalidGuardrailPolicyError("guardrail policy rule operator is not supported")
    if "value" not in node:
        raise InvalidGuardrailPolicyError("guardrail policy rule value is required")
    if operator == "in":
        value = node.get("value")
        if not isinstance(value, list) or not value:
            raise InvalidGuardrailPolicyError("guardrail policy in rule requires values")
    return 1


def validate_policy_conditions(conditions: dict[str, Any]) -> dict[str, Any]:
    if not conditions:
        return {}
    rule_count = validate_rule_node(conditions)
    if rule_count > MAX_POLICY_RULES:
        raise InvalidGuardrailPolicyError("guardrail policy has too many rules")
    return conditions


def rule_matches_context(
    rule: dict[str, Any],
    context: GuardrailEvaluationContext,
) -> bool:
    field = rule.get("field")
    context_value = guardrail_context_value(context, str(field))
    operator = rule.get("operator", "equals")
    value = rule.get("value")
    if operator == "equals":
        return values_equal(context_value, value)
    if operator == "not_equals":
        return not values_equal(context_value, value)
    if operator == "contains":
        return context_value is not None and normalize_rule_value(value) in str(context_value)
    if operator == "in":
        return isinstance(value, list) and any(values_equal(context_value, item) for item in value)
    return False


def rule_group_matches_context(
    node: dict[str, Any],
    context: GuardrailEvaluationContext,
) -> bool:
    if "rules" not in node:
        return rule_matches_context(node, context)
    rules = node.get("rules")
    if not isinstance(rules, list) or not rules:
        return True
    results = [
        rule_group_matches_context(rule, context)
        for rule in rules
        if isinstance(rule, dict)
    ]
    if len(results) != len(rules):
        return False
    if node.get("operator") == "any":
        return any(results)
    return all(results)


def policy_matches_context(
    policy: GuardrailPolicy,
    context: GuardrailEvaluationContext,
) -> bool:
    conditions = policy.conditions or {}
    if not conditions:
        return True
    return rule_group_matches_context(conditions, context)


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
    conditions = validate_policy_conditions(payload.conditions)
    name = normalize_name(payload.name)
    await ensure_unique_policy_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=name,
    )
    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.GUARDRAIL_POLICIES_PER_WORKSPACE,
                workspace_id,
            ),
            limits_service.quota_scope(
                limits_service.GUARDRAIL_POLICIES_PER_WORKSPACE_PER_USER,
                workspace_id,
                user.id,
            ),
        ],
    )
    policy_count = await repository.count_policies_for_workspace(session, workspace_id)
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.GUARDRAIL_POLICIES_PER_WORKSPACE,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=policy_count,
    )
    user_policy_count = await repository.count_policies_created_by_user_for_workspace(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.GUARDRAIL_POLICIES_PER_WORKSPACE_PER_USER,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=user_policy_count,
    )
    policy = GuardrailPolicy(
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        name=name,
        description=payload.description,
        mode=payload.mode,
        priority=payload.priority,
        conditions=conditions,
        is_active=payload.is_active,
    )
    session.add(policy)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, {"uq_guardrail_policies_workspace_name"}):
            raise DuplicateGuardrailPolicyError(
                "guardrail policy name already exists"
            ) from exc
        raise
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
    conditions = validate_policy_conditions(conditions or {})
    await ensure_unique_policy_name(
        session,
        organization_id=organization_id,
        workspace_id=policy.workspace_id,
        name=name,
        existing_policy_id=policy.id,
    )
    policy.name = name
    if "description" in update_fields and payload.description is not None:
        policy.description = payload.description
    if "mode" in update_fields and payload.mode is not None:
        policy.mode = payload.mode
    if "priority" in update_fields and payload.priority is not None:
        policy.priority = payload.priority
    if "conditions" in update_fields:
        policy.conditions = conditions
    if "is_active" in update_fields and payload.is_active is not None:
        policy.is_active = payload.is_active
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, {"uq_guardrail_policies_workspace_name"}):
            raise DuplicateGuardrailPolicyError(
                "guardrail policy name already exists"
            ) from exc
        raise
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


async def get_guardrail_settings(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailSettingsRead:
    workspace, _organization_membership, _workspace_membership = (
        await require_guardrail_scope_member(session, user, organization_id, workspace_id)
    )
    return GuardrailSettingsRead(
        workspaceId=workspace.id,
        defaultDeny=workspace.guardrail_default_deny,
    )


async def update_guardrail_settings(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: GuardrailSettingsUpdate,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailSettingsRead:
    workspace, _organization_membership, _workspace_membership = (
        await require_guardrail_scope_admin(session, user, organization_id, workspace_id)
    )
    workspace.guardrail_default_deny = payload.default_deny
    await session.flush()
    await session.refresh(workspace)
    return GuardrailSettingsRead(
        workspaceId=workspace.id,
        defaultDeny=workspace.guardrail_default_deny,
    )


async def create_starter_guardrail_policies(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: GuardrailStarterPoliciesRequest,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailStarterPoliciesResponse:
    workspace, _organization_membership, _workspace_membership = (
        await require_guardrail_scope_admin(session, user, organization_id, workspace_id)
    )
    if payload.enable_default_deny:
        workspace.guardrail_default_deny = True

    existing_policies = await repository.list_policies(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    existing_tool_schema_ids = {
        tool_schema_id
        for policy in existing_policies
        for tool_schema_id in policy_condition_tool_schema_ids(policy.conditions)
    }
    existing_names = {policy.name for policy in existing_policies}
    created: list[GuardrailPolicyRead] = []
    skipped_existing = 0
    read_only_policy_count = 0
    confirmation_policy_count = 0

    for tool_schema, installation in await agents_repository.list_workspace_available_tools(
        session,
        workspace_id=workspace_id,
    ):
        tool_schema_id = str(tool_schema.id)
        if tool_schema_id in existing_tool_schema_ids:
            skipped_existing += 1
            continue
        mode = (
            GUARDRAIL_MODE_ALLOW
            if tool_schema_read_only_hint(tool_schema.annotations)
            else GUARDRAIL_MODE_REQUIRE_CONFIRMATION
        )
        name = starter_policy_name(
            mode=mode,
            config_name=installation.config_name,
            tool_name=tool_schema.tool_name,
            tool_schema_id=tool_schema.id,
        )
        if name in existing_names:
            skipped_existing += 1
            continue
        policy = await create_guardrail_policy(
            session,
            user,
            organization_id,
            GuardrailPolicyCreate(
                name=name,
                description=starter_policy_description(mode),
                mode=mode,
                priority=100 if mode == GUARDRAIL_MODE_ALLOW else 50,
                conditions=tool_schema_condition(tool_schema.id),
                is_active=True,
            ),
            workspace_id=workspace_id,
        )
        created.append(policy)
        existing_names.add(policy.name)
        existing_tool_schema_ids.add(tool_schema_id)
        if mode == GUARDRAIL_MODE_ALLOW:
            read_only_policy_count += 1
        else:
            confirmation_policy_count += 1

    await session.flush()
    await session.refresh(workspace)
    return GuardrailStarterPoliciesResponse(
        workspaceId=workspace.id,
        defaultDeny=workspace.guardrail_default_deny,
        createdPolicies=created,
        skippedExisting=skipped_existing,
        readOnlyPolicyCount=read_only_policy_count,
        confirmationPolicyCount=confirmation_policy_count,
    )


async def simulate_guardrail_policy(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: GuardrailPolicySimulationRequest,
    *,
    workspace_id: uuid.UUID,
) -> GuardrailPolicySimulationResponse:
    await require_guardrail_scope_member(session, user, organization_id, workspace_id)
    agent = await agents_repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=payload.agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")

    installed_tools = await agents_repository.list_workspace_available_tools(
        session,
        workspace_id=workspace_id,
    )
    installed_tool = next(
        (
            (tool_schema, installation)
            for tool_schema, installation in installed_tools
            if tool_schema.id == payload.tool_schema_id
        ),
        None,
    )
    if installed_tool is None:
        reason = "Tool is not installed in this workspace."
        return GuardrailPolicySimulationResponse(
            agentId=agent.id,
            workspaceId=workspace_id,
            toolSchemaId=payload.tool_schema_id,
            installed=False,
            assigned=False,
            allowed=False,
            requiresConfirmation=False,
            blocked=True,
            status=SIMULATION_STATUS_TOOL_NOT_INSTALLED,
            reasonCode=SIMULATION_STATUS_TOOL_NOT_INSTALLED,
            reason=reason,
            decision=not_evaluated_decision_response(reason),
        )

    tool_schema, installation = installed_tool
    agent_tool_rows = await agents_repository.list_agent_tools(
        session,
        agent_id=agent.id,
    )
    assigned_tool_ids = {
        assigned_tool_schema.id
        for _assignment, assigned_tool_schema, _installation in agent_tool_rows
    }
    if tool_schema.id not in assigned_tool_ids:
        reason = "Tool is installed in this workspace but is not assigned to this agent."
        return GuardrailPolicySimulationResponse(
            agentId=agent.id,
            workspaceId=workspace_id,
            toolSchemaId=tool_schema.id,
            installationId=installation.id,
            serverName=tool_schema.server_name,
            configName=installation.config_name,
            toolName=tool_schema.tool_name,
            title=tool_schema.title,
            installed=True,
            assigned=False,
            allowed=False,
            requiresConfirmation=False,
            blocked=True,
            status=SIMULATION_STATUS_INSTALLED_NOT_ASSIGNED,
            reasonCode=SIMULATION_STATUS_INSTALLED_NOT_ASSIGNED,
            reason=reason,
            decision=not_evaluated_decision_response(reason),
        )

    decision = await evaluate_tool_call_guardrails(
        session,
        GuardrailEvaluationContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            user_id=user.id,
            agent_id=agent.id,
            conversation_id=None,
            agent_run_id=None,
            installation_id=installation.id,
            tool_schema_id=tool_schema.id,
            server_name=tool_schema.server_name,
            tool_name=tool_schema.tool_name,
            arguments=payload.arguments,
        ),
    )
    allowed = decision.mode == GUARDRAIL_MODE_ALLOW
    requires_confirmation = decision.mode == GUARDRAIL_MODE_REQUIRE_CONFIRMATION
    status = (
        SIMULATION_STATUS_ALLOWED
        if allowed
        else SIMULATION_STATUS_REQUIRES_CONFIRMATION
        if requires_confirmation
        else SIMULATION_STATUS_BLOCKED_BY_POLICY
    )
    return GuardrailPolicySimulationResponse(
        agentId=agent.id,
        workspaceId=workspace_id,
        toolSchemaId=tool_schema.id,
        installationId=installation.id,
        serverName=tool_schema.server_name,
        configName=installation.config_name,
        toolName=tool_schema.tool_name,
        title=tool_schema.title,
        installed=True,
        assigned=True,
        allowed=allowed,
        requiresConfirmation=requires_confirmation,
        blocked=not allowed and not requires_confirmation,
        status=status,
        reasonCode=status,
        reason=decision.message,
        decision=decision_response(decision),
    )


def tool_schema_condition(tool_schema_id: uuid.UUID) -> dict[str, Any]:
    return {
        "operator": "all",
        "rules": [
            {
                "field": "tool_schema_id",
                "operator": "equals",
                "value": str(tool_schema_id),
            }
        ],
    }


def tool_schema_read_only_hint(annotations: dict[str, Any] | None) -> bool:
    return isinstance(annotations, dict) and annotations.get("readOnlyHint") is True


def starter_policy_description(mode: GuardrailMode) -> str:
    if mode == GUARDRAIL_MODE_ALLOW:
        return "Generated starter rule for an assigned read-only tool."
    return "Generated starter rule that pauses mutating or unknown tools for approval."


def starter_policy_name(
    *,
    mode: GuardrailMode,
    config_name: str,
    tool_name: str,
    tool_schema_id: uuid.UUID,
) -> str:
    action = "allow" if mode == GUARDRAIL_MODE_ALLOW else "confirm"
    suffix = f" ({tool_schema_id.hex[:8]})"
    base = f"Starter {action}: {config_name} / {tool_name}"
    max_base_length = STARTER_POLICY_NAME_MAX_LENGTH - len(suffix)
    return normalize_name(f"{base[:max_base_length].rstrip()}{suffix}")


def policy_condition_tool_schema_ids(conditions: dict[str, Any]) -> set[str]:
    if not isinstance(conditions, dict):
        return set()
    if "rules" in conditions:
        rule_values: set[str] = set()
        rules = conditions.get("rules")
        if not isinstance(rules, list):
            return rule_values
        for rule in rules:
            if isinstance(rule, dict):
                rule_values.update(policy_condition_tool_schema_ids(rule))
        return rule_values
    if conditions.get("field") != "tool_schema_id":
        return set()
    operator = conditions.get("operator", "equals")
    value = conditions.get("value")
    if operator == "equals" and isinstance(value, str):
        return {value}
    if operator == "in" and isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def decision_for_policies(
    policies: list[GuardrailPolicy],
    *,
    has_active_allow_policy: bool = False,
    default_deny: bool = False,
) -> GuardrailDecision:
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
    if default_deny:
        return GuardrailDecision(
            mode=GUARDRAIL_MODE_DENY,
            message=(
                "Tool call blocked because workspace default-deny access mode is enabled "
                "and no active allow guardrail policy matched."
            ),
            matched_policy_ids=matched_policy_ids,
        )
    if has_active_allow_policy:
        return GuardrailDecision(
            mode=GUARDRAIL_MODE_DENY,
            message=(
                "Tool call blocked because it did not match any active allow "
                "guardrail policy."
            ),
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
    candidate_policies = await repository.list_matching_policies(
        session,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
    )
    has_active_allow_policy = any(
        policy.mode == GUARDRAIL_MODE_ALLOW for policy in candidate_policies
    )
    default_deny = await repository.get_workspace_guardrail_default_deny(
        session,
        workspace_id=context.workspace_id,
    )
    policies = [
        policy
        for policy in candidate_policies
        if policy_matches_context(policy, context)
    ]
    return decision_for_policies(
        policies,
        has_active_allow_policy=has_active_allow_policy,
        default_deny=default_deny,
    )
