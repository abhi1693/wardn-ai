import uuid
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits import repository
from app.modules.limits.exceptions import (
    InvalidLimitKeyError,
    InvalidLimitScopeError,
    LimitAccessDeniedError,
    LimitExceededError,
    LimitNotFoundError,
)
from app.modules.limits.models import ResourceLimit
from app.modules.limits.schemas import (
    ResourceLimitListResponse,
    ResourceLimitRead,
    ResourceLimitUpsert,
)
from app.modules.users.models import User

SCOPE_TYPES = {"organization", "workspace"}

WORKSPACES_PER_ORGANIZATION = "workspaces.per_organization"
WORKSPACES_CREATED_PER_USER = "workspaces.created_per_user"
AGENTS_PER_ORGANIZATION = "agents.per_organization"
AGENTS_PER_WORKSPACE = "agents.per_workspace"
AGENTS_PER_WORKSPACE_PER_USER = "agents.per_workspace_per_user"
WORKSPACE_CONVERSATIONS_PER_WORKSPACE = "workspace_conversations.per_workspace"
WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER = (
    "workspace_conversations.per_workspace_per_user"
)
GUARDRAIL_POLICIES_PER_WORKSPACE = "guardrail_policies.per_workspace"
GUARDRAIL_POLICIES_PER_WORKSPACE_PER_USER = "guardrail_policies.per_workspace_per_user"
MCP_CATALOG_SOURCES_PER_ORGANIZATION = "mcp_catalog_sources.per_organization"
MCP_SERVER_VERSIONS_PER_ORGANIZATION = "mcp_server_versions.per_organization"
MCP_SERVER_INSTALLATIONS_PER_WORKSPACE = "mcp_server_installations.per_workspace"
SECRET_STORES_PER_ORGANIZATION = "secret_stores.per_organization"
SECRET_STORES_PER_WORKSPACE = "secret_stores.per_workspace"
SECRET_HANDLES_PER_ORGANIZATION = "secret_handles.per_organization"
SECRET_HANDLES_PER_WORKSPACE = "secret_handles.per_workspace"
LLM_PROVIDER_CREDENTIALS_PER_ORGANIZATION = "llm_provider_credentials.per_organization"
LLM_PROVIDER_CREDENTIALS_PER_WORKSPACE = "llm_provider_credentials.per_workspace"
LLM_PROVIDER_CREDENTIALS_PER_USER = "llm_provider_credentials.per_user"

SUPPORTED_LIMIT_KEYS = {
    WORKSPACES_PER_ORGANIZATION,
    WORKSPACES_CREATED_PER_USER,
    AGENTS_PER_ORGANIZATION,
    AGENTS_PER_WORKSPACE,
    AGENTS_PER_WORKSPACE_PER_USER,
    WORKSPACE_CONVERSATIONS_PER_WORKSPACE,
    WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER,
    GUARDRAIL_POLICIES_PER_WORKSPACE,
    GUARDRAIL_POLICIES_PER_WORKSPACE_PER_USER,
    MCP_CATALOG_SOURCES_PER_ORGANIZATION,
    MCP_SERVER_VERSIONS_PER_ORGANIZATION,
    MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
    SECRET_STORES_PER_ORGANIZATION,
    SECRET_STORES_PER_WORKSPACE,
    SECRET_HANDLES_PER_ORGANIZATION,
    SECRET_HANDLES_PER_WORKSPACE,
    LLM_PROVIDER_CREDENTIALS_PER_ORGANIZATION,
    LLM_PROVIDER_CREDENTIALS_PER_WORKSPACE,
    LLM_PROVIDER_CREDENTIALS_PER_USER,
}


def require_limits_admin(user: User) -> None:
    if not user.is_superuser:
        raise LimitAccessDeniedError("only superusers can manage limits")


def normalize_limit_key(value: str) -> str:
    normalized_key = value.strip().casefold()
    if normalized_key not in SUPPORTED_LIMIT_KEYS:
        raise InvalidLimitKeyError("unsupported limit key")
    return normalized_key


def normalize_scope_type(value: str) -> str:
    normalized_type = value.strip().casefold()
    if normalized_type not in SCOPE_TYPES:
        raise InvalidLimitScopeError("invalid limit scope type")
    return normalized_type


def normalize_scope(scope_type: str, scope_id: uuid.UUID | None) -> tuple[str, uuid.UUID]:
    normalized_type = normalize_scope_type(scope_type)
    if scope_id is None:
        raise InvalidLimitScopeError(f"{normalized_type} limits require a scope id")
    return normalized_type, scope_id


def public_scope_id(scope_type: str, scope_id: uuid.UUID) -> uuid.UUID | None:
    return scope_id


def limit_response(limit: ResourceLimit) -> ResourceLimitRead:
    return ResourceLimitRead(
        id=limit.id,
        scopeType=limit.scope_type,
        scopeId=public_scope_id(limit.scope_type, limit.scope_id),
        limitKey=limit.limit_key,
        value=limit.value,
        createdAt=limit.created_at,
        updatedAt=limit.updated_at,
    )


async def list_resource_limits(
    session: AsyncSession,
    user: User,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    limit_key: str | None = None,
) -> ResourceLimitListResponse:
    require_limits_admin(user)
    normalized_scope_type = None
    normalized_scope_id = None
    if scope_type is not None:
        normalized_scope_type = normalize_scope_type(scope_type)
        if scope_id is not None:
            normalized_scope_id = scope_id
    limits = await repository.list_limits(
        session,
        scope_type=normalized_scope_type,
        scope_id=normalized_scope_id,
        limit_key=normalize_limit_key(limit_key) if limit_key is not None else None,
    )
    return ResourceLimitListResponse(limits=[limit_response(limit) for limit in limits])


async def upsert_resource_limit(
    session: AsyncSession,
    user: User,
    payload: ResourceLimitUpsert,
) -> ResourceLimitRead:
    require_limits_admin(user)
    scope_type, scope_id = normalize_scope(payload.scope_type, payload.scope_id)
    limit_key = normalize_limit_key(payload.limit_key)
    limit = await repository.get_limit(
        session,
        scope_type=scope_type,
        scope_id=scope_id,
        limit_key=limit_key,
    )
    if limit is None:
        limit = ResourceLimit(
            scope_type=scope_type,
            scope_id=scope_id,
            limit_key=limit_key,
            value=payload.value,
        )
        session.add(limit)
    else:
        limit.value = payload.value
    await session.flush()
    await session.refresh(limit)
    return limit_response(limit)


async def delete_resource_limit(
    session: AsyncSession,
    user: User,
    limit_id: uuid.UUID,
) -> None:
    require_limits_admin(user)
    limit = await repository.get_limit_by_id(session, limit_id)
    if limit is None:
        raise LimitNotFoundError("limit not found")
    await session.delete(limit)
    await session.flush()


async def effective_limit(
    session: AsyncSession,
    *,
    limit_key: str,
    scope_chain: Iterable[tuple[str, uuid.UUID | None]],
) -> ResourceLimit | None:
    if not hasattr(session, "execute"):
        return None
    normalized_key = normalize_limit_key(limit_key)
    for scope_type, scope_id in scope_chain:
        normalized_type, normalized_id = normalize_scope(scope_type, scope_id)
        limit = await repository.get_limit(
            session,
            scope_type=normalized_type,
            scope_id=normalized_id,
            limit_key=normalized_key,
        )
        if limit is not None:
            return limit
    return None


async def require_limit_available(
    session: AsyncSession,
    *,
    limit_key: str,
    scope_chain: Iterable[tuple[str, uuid.UUID | None]],
    current_count: int,
    requested: int = 1,
) -> None:
    limit = await effective_limit(session, limit_key=limit_key, scope_chain=scope_chain)
    if limit is None:
        return
    if current_count + requested > limit.value:
        raise LimitExceededError(
            f"{limit.limit_key} limit exceeded: {current_count}/{limit.value}"
        )
