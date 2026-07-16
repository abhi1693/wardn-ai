import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
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
from app.modules.limits import service as limits_service
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
    candidate_policies = await repository.list_matching_policies(
        session,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
    )
    policies = [
        policy
        for policy in candidate_policies
        if policy_matches_context(policy, context)
    ]
    return decision_for_policies(policies)
