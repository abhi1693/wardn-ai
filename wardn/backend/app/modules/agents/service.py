import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPageMetadata
from app.modules.agents import repository
from app.modules.agents.approvals import (
    approval_continuation_prompt as approval_continuation_prompt,
)
from app.modules.agents.approvals import (
    conversation_message_to_chat_message as conversation_message_to_chat_message,
)
from app.modules.agents.approvals import (
    decide_agent_tool_approval as decide_agent_tool_approval,
)
from app.modules.agents.approvals import (
    generate_approval_continuation_message as generate_approval_continuation_message,
)
from app.modules.agents.approvals import (
    get_agent_tool_approval as get_agent_tool_approval,
)
from app.modules.agents.chat_orchestrator import (
    chat_stream_error_text as chat_stream_error_text,
)
from app.modules.agents.chat_orchestrator import (
    conversation_id_from_payload as conversation_id_from_payload,
)
from app.modules.agents.chat_orchestrator import (
    denied_mcp_tool_matches,
    filter_agent_runtime_tools_for_guardrails,
    latest_user_message,
    persisted_agent_chat_stream,
    preflight_blocked_tool_stream,
)
from app.modules.agents.chat_orchestrator import (
    message_requests_denied_mcp_tool as message_requests_denied_mcp_tool,
)
from app.modules.agents.chat_orchestrator import (
    persist_chat_turn_user_message as persist_chat_turn_user_message,
)
from app.modules.agents.chat_orchestrator import (
    record_agent_llm_usage as record_agent_llm_usage,
)
from app.modules.agents.chat_orchestrator import (
    refresh_agent_chat_credential as refresh_agent_chat_credential,
)
from app.modules.agents.chat_orchestrator import (
    require_agent_llm_budget_available as require_agent_llm_budget_available,
)
from app.modules.agents.chat_orchestrator import (
    run_agent_chat as run_agent_chat,
)
from app.modules.agents.chat_orchestrator import (
    stream_chatgpt_codex_response_text as stream_chatgpt_codex_response_text,
)
from app.modules.agents.chat_orchestrator import (
    stream_with_capability_diagnosis as stream_with_capability_diagnosis,
)
from app.modules.agents.chat_orchestrator import (
    ui_message_sse_chunk as ui_message_sse_chunk,
)
from app.modules.agents.conversations import AgentSessionFactory
from app.modules.agents.dynamic_tools import (
    AGENT_RUN_TOOL_TOOL_NAME as AGENT_RUN_TOOL_TOOL_NAME,
)
from app.modules.agents.dynamic_tools import (
    AGENT_SEARCH_TOOLS_TOOL_NAME as AGENT_SEARCH_TOOLS_TOOL_NAME,
)
from app.modules.agents.dynamic_tools import (
    agent_dynamic_function_tools as agent_dynamic_function_tools,
)
from app.modules.agents.dynamic_tools import (
    execute_agent_search_tools as execute_agent_search_tools,
)
from app.modules.agents.dynamic_tools import (
    resolve_agent_run_tool_call as resolve_agent_run_tool_call,
)
from app.modules.agents.exceptions import (
    AgentNotFoundError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.mappers import (
    AGENT_RUN_PAYLOAD_STRING_MAX_CHARS as AGENT_RUN_PAYLOAD_STRING_MAX_CHARS,
)
from app.modules.agents.mappers import (
    agent_response,
    agent_run_response,
    agent_run_step_response,
    conversation_message_response,
    conversation_response,
    sanitize_run_payload,
)
from app.modules.agents.models import (
    Agent,
)
from app.modules.agents.provider_clients import (
    CODEX_COMPAT_USER_AGENT as CODEX_COMPAT_USER_AGENT,
)
from app.modules.agents.provider_clients import (
    CODEX_COMPAT_VERSION as CODEX_COMPAT_VERSION,
)
from app.modules.agents.provider_clients import (
    DEFAULT_CODEX_COMPAT_VERSION as DEFAULT_CODEX_COMPAT_VERSION,
)
from app.modules.agents.provider_clients import (
    agent_runtime_tools,
    provider_messages,
    text_from_chat_message,
)
from app.modules.agents.provider_clients import (
    chatgpt_codex_messages as chatgpt_codex_messages,
)
from app.modules.agents.provider_clients import (
    chatgpt_codex_request_body as chatgpt_codex_request_body,
)
from app.modules.agents.provider_clients import (
    llm_usage_from_completed_event as llm_usage_from_completed_event,
)
from app.modules.agents.provider_clients import (
    reasoning_request_for_model as reasoning_request_for_model,
)
from app.modules.agents.provider_clients import (
    reasoning_summaries_from_openai_event as reasoning_summaries_from_openai_event,
)
from app.modules.agents.provider_clients import (
    sse_payloads as sse_payloads,
)
from app.modules.agents.provider_clients import (
    text_delta_from_openai_event as text_delta_from_openai_event,
)
from app.modules.agents.provider_clients import (
    tool_calls_from_event as tool_calls_from_event,
)
from app.modules.agents.provider_clients import (
    validate_agent_model as validate_agent_model,
)
from app.modules.agents.provider_clients import (
    validate_provider_credential as validate_provider_credential,
)
from app.modules.agents.provider_clients import (
    websocket_error_message as websocket_error_message,
)
from app.modules.agents.schemas import (
    AgentAvailableServerRead,
    AgentAvailableToolListResponse,
    AgentAvailableToolRead,
    AgentChatRequest,
    AgentConversationResponse,
    AgentListResponse,
    AgentRead,
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentSkillAgentRead,
    AgentSkillCatalogResponse,
    AgentSkillPermissionRead,
    AgentSkillRead,
    AgentSkillRecommendationRead,
    AgentSkillSearchResponse,
    AgentSkillSearchResultRead,
    AgentSkillWorkflowRead,
    WorkspaceAgentModelUpdate,
)
from app.modules.agents.skills import (
    WARDN_FIND_SKILLS_DESCRIPTION,
    WARDN_FIND_SKILLS_ID,
    WARDN_FIND_SKILLS_NAME,
    WARDN_FIND_SKILLS_SOURCE,
    WARDN_FIND_SKILLS_SOURCE_URL,
    WARDN_FIND_SKILLS_URL,
    fetch_wardn_hub_skill_audit,
    find_skills_permission_summaries,
    normalize_agent_skill_ids,
    rejecting_audit_summary,
    search_wardn_hub_skills,
    skill_audit_summary,
)
from app.modules.agents.tool_execution import (
    AGENT_TOOL_BLOCKED_PREFIX as AGENT_TOOL_BLOCKED_PREFIX,
)
from app.modules.agents.tool_execution import (
    AGENT_TOOL_CONFIRMATION_PREFIX as AGENT_TOOL_CONFIRMATION_PREFIX,
)
from app.modules.agents.tool_execution import (
    AGENT_TOOL_TARGET_SAFETY_PREFIX as AGENT_TOOL_TARGET_SAFETY_PREFIX,
)
from app.modules.agents.tool_execution import (
    execute_agent_tool_call as execute_agent_tool_call,
)
from app.modules.agents.types import AgentChatProviderError as AgentChatProviderError
from app.modules.agents.types import (
    AgentChatReasoningSummaryEvent as AgentChatReasoningSummaryEvent,
)
from app.modules.agents.types import AgentChatTextEvent as AgentChatTextEvent
from app.modules.agents.types import (
    AgentChatToolActivityEvent as AgentChatToolActivityEvent,
)
from app.modules.agents.types import (
    AgentInstalledTool,
)
from app.modules.agents.types import AgentToolCall as AgentToolCall
from app.modules.agents.types import AgentToolExecutionResult as AgentToolExecutionResult
from app.modules.limits import service as limits_service
from app.modules.llm_providers import repository as llm_provider_repository
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.service import OPENAI_API_KEY_PROVIDER as OPENAI_API_KEY_PROVIDER
from app.modules.llm_providers.service import OPENAI_CHATGPT_PROVIDER as OPENAI_CHATGPT_PROVIDER
from app.modules.llm_providers.service import list_models_for_credential, user_can_see_credential
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import repository as mcp_registry_repository
from app.modules.mcp_registry import tool_repository as mcp_tool_repository
from app.modules.mcp_registry.exceptions import MCPServerInstallationFailedError
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas_for_installation
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.observability import service as observability_service
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)

AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS = 40_000
QUICK_START_AGENT_NAME = "Workspace Assistant"
QUICK_START_AGENT_DESCRIPTION = "Default assistant for workspace chat."
QUICK_START_AGENT_INSTRUCTIONS = (
    "You are a workspace assistant. Use available tools when they help answer accurately. "
    "When no obvious workflow exists, search Wardn Hub skills for audited guidance, then use "
    "workspace tools through Wardn's tool search and execution flow. Ask before destructive "
    "actions."
)
GUIDED_SKILL_WORKFLOWS = [
    {
        "id": "kubernetes-ops",
        "title": "Kubernetes ops",
        "description": (
            "Use cluster-aware runbooks for namespaces, workloads, ingress, and policy checks."
        ),
        "query": "kubernetes ops",
        "required_connection_hints": ["kubernetes", "rancher", "cilium", "calico"],
    },
    {
        "id": "email-triage",
        "title": "Email triage",
        "description": (
            "Find urgent mail, summarize threads, and prepare responses with mailbox tools."
        ),
        "query": "email triage",
        "required_connection_hints": ["gmail", "mail"],
    },
    {
        "id": "gsc-checks",
        "title": "GSC checks",
        "description": (
            "Review indexing, sitemap, performance, and ownership status with GSC tools."
        ),
        "query": "search console",
        "required_connection_hints": ["gsc", "search console"],
    },
    {
        "id": "github-reviews",
        "title": "GitHub reviews",
        "description": (
            "Build a review queue, inspect PR context, and keep review actions read-only "
            "by default."
        ),
        "query": "github review",
        "required_connection_hints": ["github", "pull request", "repo"],
    },
]
SKILL_RECOMMENDATION_RULES = [
    {
        "id": "kubernetes-ops",
        "title": "Kubernetes ops skills",
        "description": (
            "Recommended because this workspace has Kubernetes or Rancher-style connections."
        ),
        "query": "kubernetes ops",
        "keywords": ("kubernetes", "k8s", "rancher", "cilium", "calico"),
        "workflow_ids": ["kubernetes-ops"],
    },
    {
        "id": "email-triage",
        "title": "Email triage skills",
        "description": "Recommended because this workspace has mailbox connections.",
        "query": "email triage",
        "keywords": ("gmail", "mail", "email", "inbox"),
        "workflow_ids": ["email-triage"],
    },
    {
        "id": "gsc-checks",
        "title": "Google Search Console skills",
        "description": "Recommended because this workspace has search console or SEO connections.",
        "query": "search console",
        "keywords": ("google-search-console", "search console", "gsc", "seo"),
        "workflow_ids": ["gsc-checks"],
    },
    {
        "id": "github-reviews",
        "title": "GitHub review skills",
        "description": "Recommended because this workspace has repository or PR connections.",
        "query": "github review",
        "keywords": ("github", "gitlab", "pull request", "repo"),
        "workflow_ids": ["github-reviews"],
    },
]


@dataclass(frozen=True)
class AgentToolRefreshFailure:
    installation_id: uuid.UUID
    server_name: str
    server_version: str
    config_name: str
    error_type: str
    error: str


def agent_log_extra(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    scope: str | None = None,
) -> dict[str, str | None]:
    return {
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id) if workspace_id else None,
        "agent_id": str(agent_id) if agent_id else None,
        "user_id": str(user_id) if user_id else None,
        "agent_scope": scope,
    }


async def require_agent_scope_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    scope: str,
    workspace_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if scope == "organization":
        await require_organization_admin(session, user, organization_id)
        if workspace_id is not None:
            raise InvalidAgentScopeError("organization-scoped agents cannot include a workspace")
        return None
    if scope == "workspace":
        if workspace_id is None:
            raise InvalidAgentScopeError("workspace-scoped agents require a workspace")
        await require_workspace_admin(session, user, organization_id, workspace_id)
        return workspace_id
    raise InvalidAgentScopeError("invalid agent scope")


async def require_agent_run_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    scope: str,
    workspace_id: uuid.UUID | None,
) -> None:
    if scope == "organization":
        await require_organization_member(session, user, organization_id)
        if workspace_id is not None:
            raise InvalidAgentScopeError("organization-scoped agents cannot include a workspace")
        return
    if scope == "workspace":
        if workspace_id is None:
            raise InvalidAgentScopeError("workspace-scoped agents require a workspace")
        await require_workspace_member(session, user, organization_id, workspace_id)
        return
    raise InvalidAgentScopeError("invalid agent scope")


async def list_agents(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AgentListResponse:
    if workspace_id is None:
        await require_organization_member(session, user, organization_id)
    else:
        await require_workspace_member(session, user, organization_id, workspace_id)
    rows, next_cursor = await repository.list_agents(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user.id,
        is_superuser=user.is_superuser,
        cursor=cursor,
        limit=limit,
    )
    return AgentListResponse(
        agents=[
            agent_response(agent, server_count=server_count, tool_count=tool_count)
            for agent, server_count, tool_count in rows
        ],
        metadata=CursorPageMetadata(count=len(rows), nextCursor=next_cursor),
    )


async def get_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> AgentRead:
    if workspace_id is None:
        await require_organization_member(session, user, organization_id)
    else:
        await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    return agent_response(
        agent,
        server_count=await repository.count_agent_servers(session, agent.id),
        tool_count=await repository.count_agent_tools(session, agent.id),
    )


async def get_agent_model_for_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> tuple[Agent, LLMProviderCredential]:
    if workspace_id is None:
        await require_organization_member(session, user, organization_id)
    else:
        await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    await require_agent_run_permission(
        session,
        user,
        organization_id,
        scope=agent.scope,
        workspace_id=agent.workspace_id,
    )
    if agent.provider_credential_id is None:
        raise InvalidAgentScopeError("agent requires an LLM credential before chat")
    if not agent.model_name:
        raise InvalidAgentScopeError("agent requires a model before chat")
    credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=agent.workspace_id,
        provider_credential_id=agent.provider_credential_id,
    )
    if credential is None:
        raise InvalidAgentScopeError("agent requires an LLM credential before chat")
    return agent, credential


async def require_agent_create_limit(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> None:
    quota_scopes = agent_quota_scopes(user, organization_id, workspace_id)
    await limits_service.lock_quota_capacity(session, quota_scopes)
    organization_agent_count = await repository.count_active_agents_for_organization(
        session,
        organization_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.AGENTS_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=organization_agent_count,
    )
    if workspace_id is None:
        return

    workspace_agent_count = await repository.count_active_agents_for_workspace(
        session,
        workspace_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.AGENTS_PER_WORKSPACE,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=workspace_agent_count,
    )
    user_workspace_agent_count = (
        await repository.count_active_agents_created_by_user_for_workspace(
            session,
            workspace_id=workspace_id,
            user_id=user.id,
        )
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.AGENTS_PER_WORKSPACE_PER_USER,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=user_workspace_agent_count,
    )


def agent_quota_scopes(
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> list[limits_service.QuotaScope]:
    scopes = [
        limits_service.quota_scope(
            limits_service.AGENTS_PER_ORGANIZATION,
            organization_id,
        )
    ]
    if workspace_id is not None:
        scopes.extend(
            [
                limits_service.quota_scope(
                    limits_service.AGENTS_PER_WORKSPACE,
                    workspace_id,
                ),
                limits_service.quota_scope(
                    limits_service.AGENTS_PER_WORKSPACE_PER_USER,
                    workspace_id,
                    user.id,
                ),
            ]
        )
    return scopes


def credential_visible_for_workspace_quick_start(
    user: User,
    credential: LLMProviderCredential,
    workspace_id: uuid.UUID,
) -> bool:
    if not credential.is_active or not user_can_see_credential(user, credential):
        return False
    if credential.visibility == "workspace":
        return credential.workspace_id == workspace_id
    return credential.workspace_id is None


def quick_start_credential_sort_key(credential: LLMProviderCredential) -> tuple[int, str, str]:
    scope_rank = {"workspace": 0, "organization": 1, "user": 2}.get(credential.visibility, 3)
    return (scope_rank, credential.provider, credential.name.casefold())


async def select_quick_start_credential_and_model(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[LLMProviderCredential, str]:
    credentials = await llm_provider_repository.list_credentials(
        session,
        organization_id=organization_id,
    )
    candidates = sorted(
        (
            credential
            for credential in credentials
            if credential_visible_for_workspace_quick_start(user, credential, workspace_id)
        ),
        key=quick_start_credential_sort_key,
    )
    for credential in candidates:
        try:
            models = await list_models_for_credential(session, credential)
        except Exception:
            continue
        first_model = next((model for model in models.models if model.id.strip()), None)
        if first_model is not None:
            return credential, first_model.id
    raise InvalidAgentScopeError("no usable LLM credential is available for workspace chat")


async def quick_start_agent_needs_model_selection(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent: Agent,
) -> bool:
    if agent.provider_credential_id is None or not agent.model_name:
        return True
    try:
        credential = await validate_provider_credential(
            session,
            user,
            organization_id,
            agent_workspace_id=agent.workspace_id,
            provider_credential_id=agent.provider_credential_id,
        )
        await validate_agent_model(session, credential, agent.model_name)
    except InvalidAgentScopeError:
        return True
    return False


async def sync_quick_start_agent_tools(
    session: AsyncSession,
    agent: Agent,
    workspace_id: uuid.UUID,
) -> None:
    installations = await mcp_registry_repository.list_installations(
        session,
        workspace_id=workspace_id,
    )
    enabled_installations = [
        installation for installation in installations if installation.status == "enabled"
    ]
    await repository.replace_agent_tools(
        session,
        agent_id=agent.id,
        server_assignments=[(installation, True, []) for installation in enabled_installations],
    )


def skill_permission_reads() -> list[AgentSkillPermissionRead]:
    return [
        AgentSkillPermissionRead(**permission)
        for permission in find_skills_permission_summaries()
    ]


def agent_skill_agent_read(agent: Agent) -> AgentSkillAgentRead:
    return AgentSkillAgentRead(
        id=agent.id,
        name=agent.name,
        enabled_skill_ids=normalize_agent_skill_ids(agent.skill_ids or []),
    )


async def find_skills_audit_metadata() -> dict[str, Any]:
    try:
        payload = await asyncio.wait_for(
            fetch_wardn_hub_skill_audit(WARDN_FIND_SKILLS_ID),
            timeout=5.0,
        )
    except Exception as exc:
        return {
            "audit_status": "unknown",
            "audit_score": None,
            "audit_rank": None,
            "audit_summary": "",
            "health_status": "unhealthy",
            "health_detail": f"Wardn Hub audit check failed: {exc}",
        }

    audit = skill_audit_summary(payload.get("audit"))
    if not audit:
        return {
            "audit_status": "unknown",
            "audit_score": None,
            "audit_rank": None,
            "audit_summary": "",
            "health_status": "unknown",
            "health_detail": "Wardn Hub did not return an audit summary.",
        }

    audit_status = str(audit.get("status") or "unknown")
    health_status = "unhealthy" if rejecting_audit_summary(audit) else "healthy"
    health_detail = str(audit.get("summary") or "")
    return {
        "audit_status": audit_status,
        "audit_score": audit.get("score"),
        "audit_rank": audit.get("rank"),
        "audit_summary": health_detail,
        "health_status": health_status,
        "health_detail": health_detail or f"Wardn Hub audit status is {audit_status}.",
    }


def find_skills_read(
    *,
    agents: list[Agent],
    audit_metadata: dict[str, Any],
) -> AgentSkillRead:
    enabled_agents = [
        agent
        for agent in agents
        if WARDN_FIND_SKILLS_ID in normalize_agent_skill_ids(agent.skill_ids or [])
    ]
    return AgentSkillRead(
        id=WARDN_FIND_SKILLS_ID,
        name=WARDN_FIND_SKILLS_NAME,
        description=WARDN_FIND_SKILLS_DESCRIPTION,
        url=WARDN_FIND_SKILLS_URL,
        source=WARDN_FIND_SKILLS_SOURCE,
        source_url=WARDN_FIND_SKILLS_SOURCE_URL,
        source_owner="abhi1693",
        source_name="wardn-hub",
        audit_status=str(audit_metadata.get("audit_status") or "unknown"),
        audit_score=audit_metadata.get("audit_score"),
        audit_rank=audit_metadata.get("audit_rank"),
        audit_summary=str(audit_metadata.get("audit_summary") or ""),
        permissions=skill_permission_reads(),
        installed=bool(enabled_agents),
        temporary=False,
        enabled_agent_ids=[agent.id for agent in enabled_agents],
        enabled_agent_names=[agent.name for agent in enabled_agents],
        health_status=audit_metadata.get("health_status") or "unknown",
        health_detail=str(audit_metadata.get("health_detail") or ""),
    )


def installation_connection_name(installation: MCPServerInstallation) -> str:
    return f"{installation.server_name} ({installation.config_name})"


def installed_connection_text(installation: MCPServerInstallation) -> str:
    parts = [
        installation.server_name,
        installation.config_name,
        installation.installed_version,
    ]
    config = installation.runtime_config if isinstance(installation.runtime_config, dict) else {}
    for value in config.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if isinstance(item, str))
    return " ".join(parts).casefold()


def workspace_skill_recommendations(
    installations: list[MCPServerInstallation],
) -> list[AgentSkillRecommendationRead]:
    recommendations: list[AgentSkillRecommendationRead] = []
    for rule in SKILL_RECOMMENDATION_RULES:
        keywords = rule["keywords"]
        matched = [
            installation
            for installation in installations
            if installation.status == "enabled"
            and any(keyword in installed_connection_text(installation) for keyword in keywords)
        ]
        if not matched:
            continue
        connection_names = [
            installation_connection_name(installation) for installation in matched
        ]
        recommendations.append(
            AgentSkillRecommendationRead(
                id=rule["id"],
                title=rule["title"],
                description=rule["description"],
                query=rule["query"],
                connection_ids=[installation.id for installation in matched],
                connection_names=connection_names,
                workflow_ids=list(rule["workflow_ids"]),
            )
        )
    return recommendations


def workspace_guided_skill_workflows() -> list[AgentSkillWorkflowRead]:
    return [AgentSkillWorkflowRead(**workflow) for workflow in GUIDED_SKILL_WORKFLOWS]


async def list_workspace_skills(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentSkillCatalogResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    rows, _next_cursor = await repository.list_agents(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user.id,
        is_superuser=user.is_superuser,
        include_inactive=False,
        limit=100,
    )
    agents = [agent for agent, _server_count, _tool_count in rows]
    installations = await mcp_registry_repository.list_installations(
        session,
        workspace_id=workspace_id,
    )
    audit_metadata = await find_skills_audit_metadata()
    return AgentSkillCatalogResponse(
        skills=[find_skills_read(agents=agents, audit_metadata=audit_metadata)],
        agents=[agent_skill_agent_read(agent) for agent in agents],
        recommendations=workspace_skill_recommendations(installations),
        guided_workflows=workspace_guided_skill_workflows(),
    )


def skill_search_result_read(item: dict[str, Any]) -> AgentSkillSearchResultRead:
    return AgentSkillSearchResultRead(
        id=str(item.get("id") or ""),
        name=str(item.get("name") or ""),
        description=str(item.get("description") or ""),
        url=str(item.get("url") or ""),
        source=str(item.get("source") or ""),
        source_owner=str(item.get("sourceOwner") or ""),
        source_name=str(item.get("sourceName") or ""),
        is_official=bool(item.get("isOfficial")),
        installs=int(item.get("installs") or 0),
        audit_status=item.get("auditStatus"),
        audit_score=item.get("auditScore"),
        audit_rank=item.get("auditRank"),
        installed=item.get("id") == WARDN_FIND_SKILLS_ID,
        temporary=item.get("id") != WARDN_FIND_SKILLS_ID,
        permissions=skill_permission_reads(),
    )


async def search_workspace_skills(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    query: str,
    limit: int,
) -> AgentSkillSearchResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    try:
        payload = await search_wardn_hub_skills({"query": query, "limit": limit})
    except ValueError as exc:
        raise InvalidAgentScopeError(str(exc)) from exc
    return AgentSkillSearchResponse(
        query=str(payload.get("query") or query),
        count=int(payload.get("count") or 0),
        results=[
            skill_search_result_read(item)
            for item in payload.get("results", [])
            if isinstance(item, dict)
        ],
    )


async def quick_start_workspace_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentConversationResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    await limits_service.lock_quota_capacity(
        session,
        agent_quota_scopes(user, organization_id, workspace_id),
    )
    agent = await repository.get_agent_by_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=QUICK_START_AGENT_NAME,
    )
    if agent is None:
        await require_agent_create_limit(session, user, organization_id, workspace_id)
        credential, model_name = await select_quick_start_credential_and_model(
            session,
            user,
            organization_id,
            workspace_id,
        )
        agent = Agent(
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_by_id=user.id,
            provider_credential_id=credential.id,
            name=QUICK_START_AGENT_NAME,
            description=QUICK_START_AGENT_DESCRIPTION,
            instructions=QUICK_START_AGENT_INSTRUCTIONS,
            scope="workspace",
            model_name=model_name,
            skill_ids=[WARDN_FIND_SKILLS_ID],
            is_active=True,
        )
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
    else:
        changed = False
        if await quick_start_agent_needs_model_selection(
            session,
            user,
            organization_id,
            agent,
        ):
            credential, model_name = await select_quick_start_credential_and_model(
                session,
                user,
                organization_id,
                workspace_id,
            )
            agent.provider_credential_id = credential.id
            agent.model_name = model_name
            changed = True
        if not agent.instructions.strip():
            agent.instructions = QUICK_START_AGENT_INSTRUCTIONS
            changed = True
        if not agent.is_active:
            agent.is_active = True
            changed = True
        skill_ids = normalize_agent_skill_ids(agent.skill_ids or [])
        if WARDN_FIND_SKILLS_ID not in skill_ids:
            agent.skill_ids = [*skill_ids, WARDN_FIND_SKILLS_ID]
            changed = True
        if changed:
            await session.flush()
            await session.refresh(agent)
    await sync_quick_start_agent_tools(session, agent, workspace_id)
    server_count = await repository.count_agent_servers(session, agent.id)
    tool_count = await repository.count_agent_tools(session, agent.id)
    await require_workspace_conversation_create_limit(session, user, organization_id, workspace_id)
    conversation = await repository.create_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        created_by_id=user.id,
    )
    return AgentConversationResponse(
        agent=agent_response(agent, server_count=server_count, tool_count=tool_count),
        conversation=conversation_response(conversation),
        messages=[],
    )


async def update_workspace_assistant_model(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: WorkspaceAgentModelUpdate,
) -> AgentRead:
    await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope="workspace",
        workspace_id=workspace_id,
    )
    provider_credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=workspace_id,
        provider_credential_id=payload.provider_credential_id,
    )
    if provider_credential is None:
        raise InvalidAgentScopeError("workspace assistant requires an LLM credential")
    model_name = await validate_agent_model(
        session,
        provider_credential,
        payload.model_name,
    )
    agent = await repository.get_agent_by_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=QUICK_START_AGENT_NAME,
    )
    if agent is None:
        await require_agent_create_limit(session, user, organization_id, workspace_id)
        agent = Agent(
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_by_id=user.id,
            provider_credential_id=provider_credential.id,
            name=QUICK_START_AGENT_NAME,
            description=QUICK_START_AGENT_DESCRIPTION,
            instructions=QUICK_START_AGENT_INSTRUCTIONS,
            scope="workspace",
            model_name=model_name,
            skill_ids=[WARDN_FIND_SKILLS_ID],
            is_active=True,
        )
        session.add(agent)
    else:
        agent.provider_credential_id = provider_credential.id
        agent.model_name = model_name
        agent.scope = "workspace"
        agent.workspace_id = workspace_id
        if not agent.description.strip():
            agent.description = QUICK_START_AGENT_DESCRIPTION
        if not agent.instructions.strip():
            agent.instructions = QUICK_START_AGENT_INSTRUCTIONS
        skill_ids = normalize_agent_skill_ids(agent.skill_ids or [])
        if WARDN_FIND_SKILLS_ID not in skill_ids:
            agent.skill_ids = [*skill_ids, WARDN_FIND_SKILLS_ID]
        agent.is_active = True
    await session.flush()
    await session.refresh(agent)
    await sync_quick_start_agent_tools(session, agent, workspace_id)
    logger.info(
        "Updated workspace assistant model.",
        extra={
            **agent_log_extra(
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_id=agent.id,
                user_id=user.id,
                scope=agent.scope,
            ),
            "llm_provider_credential_id": str(agent.provider_credential_id),
            "agent_model_name": agent.model_name,
        },
    )
    return agent_response(
        agent,
        server_count=await repository.count_agent_servers(session, agent.id),
        tool_count=await repository.count_agent_tools(session, agent.id),
    )


async def require_workspace_conversation_create_limit(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE,
                workspace_id,
            ),
            limits_service.quota_scope(
                limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER,
                workspace_id,
                user.id,
            ),
        ],
    )
    workspace_conversation_count = await repository.count_active_workspace_conversations(
        session,
        workspace_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=workspace_conversation_count,
    )
    user_workspace_conversation_count = (
        await repository.count_active_workspace_conversations_created_by_user(
            session,
            workspace_id=workspace_id,
            user_id=user.id,
        )
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=user_workspace_conversation_count,
    )


async def get_workspace_conversation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> AgentConversationResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    conversation = await repository.get_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise AgentNotFoundError("conversation not found")
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=conversation.agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    messages = await repository.list_conversation_messages(
        session,
        conversation_id=conversation.id,
    )
    return AgentConversationResponse(
        agent=agent_response(
            agent,
            server_count=await repository.count_agent_servers(session, agent.id),
            tool_count=await repository.count_agent_tools(session, agent.id),
        ),
        conversation=conversation_response(conversation),
        messages=[conversation_message_response(message) for message in messages],
    )


async def list_workspace_agent_runs(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentRunListResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    runs = await repository.list_agent_runs(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    usage_summaries = await observability_service.agent_run_usage_summaries(
        session,
        agent_run_ids=[agent_run.id for agent_run in runs],
    )
    provider_triggers = await repository.list_chat_provider_triggers_by_conversation(
        session,
        conversation_ids=[
            agent_run.conversation_id
            for agent_run in runs
            if agent_run.conversation_id is not None
        ],
    )
    return AgentRunListResponse(
        runs=[
            agent_run_response(
                agent_run,
                usage_summaries.get(agent_run.id),
                trigger_type=response_trigger_type(agent_run, provider_triggers),
            )
            for agent_run in runs
        ]
    )


async def get_workspace_agent_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> AgentRunDetailResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    agent_run = await repository.get_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
    )
    if agent_run is None:
        raise AgentNotFoundError("agent run not found")
    steps = await repository.list_agent_run_steps(session, agent_run_id=agent_run.id)
    usage_summary = await observability_service.agent_run_usage_summary(
        session,
        agent_run_id=agent_run.id,
    )
    trace_id, span_id = await observability_service.agent_run_trace_ids(
        session,
        agent_run_id=agent_run.id,
    )
    provider_triggers = await repository.list_chat_provider_triggers_by_conversation(
        session,
        conversation_ids=[agent_run.conversation_id] if agent_run.conversation_id else [],
    )
    return AgentRunDetailResponse(
        run=agent_run_response(
            agent_run,
            usage_summary,
            trace_id=trace_id,
            span_id=span_id,
            trigger_type=response_trigger_type(agent_run, provider_triggers),
        ),
        steps=[agent_run_step_response(step) for step in steps],
    )


def normalize_agent_run_trigger_type(trigger_type: str) -> str:
    if trigger_type == "whatsapp_local":
        return "whatsapp"
    return trigger_type


def response_trigger_type(
    agent_run,
    provider_triggers: dict[uuid.UUID, str],
) -> str:
    trigger_type = agent_run.trigger_type
    if trigger_type == "chat" and agent_run.conversation_id is not None:
        trigger_type = provider_triggers.get(agent_run.conversation_id, trigger_type)
    return normalize_agent_run_trigger_type(trigger_type)


def available_tool_response(
    tool_schema: MCPServerToolSchema,
    installation: MCPServerInstallation,
) -> AgentAvailableToolRead:
    if tool_schema.workspace_id is None or tool_schema.installation_id is None:
        raise InvalidAgentToolAssignmentError("tool is not workspace assignable")
    return AgentAvailableToolRead(
        toolSchemaId=tool_schema.id,
        installationId=installation.id,
        workspaceId=tool_schema.workspace_id,
        serverName=tool_schema.server_name,
        configName=installation.config_name,
        toolName=tool_schema.tool_name,
        title=tool_schema.title,
        description=tool_schema.description,
        inputSchema=tool_schema.input_schema,
        outputSchema=tool_schema.output_schema,
        annotations=tool_schema.annotations,
    )


def available_server_response(installation: MCPServerInstallation) -> AgentAvailableServerRead:
    return AgentAvailableServerRead(
        installationId=installation.id,
        workspaceId=installation.workspace_id,
        serverName=installation.server_name,
        configName=installation.config_name,
        installedVersion=installation.installed_version,
        status=installation.status,
    )


async def list_available_agent_tools(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentAvailableToolListResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    installations = await mcp_registry_repository.list_installations(
        session,
        workspace_id=workspace_id,
    )
    rows = await repository.list_workspace_available_tools(session, workspace_id=workspace_id)
    return AgentAvailableToolListResponse(
        servers=[
            available_server_response(installation)
            for installation in installations
            if installation.status == "enabled"
        ],
        tools=[
            available_tool_response(tool_schema, installation)
            for tool_schema, installation in rows
        ]
    )




async def refresh_wildcard_agent_server_tools(
    session: AsyncSession,
    agent_id: uuid.UUID,
) -> list[AgentToolRefreshFailure]:
    rows = await repository.list_agent_wildcard_server_version_rows(session, agent_id=agent_id)
    failures: list[AgentToolRefreshFailure] = []
    for _assignment, installation, server in rows:
        try:
            cached_tool_count = await mcp_tool_repository.count_active_tool_schemas(
                session,
                installation_id=installation.id,
                server_name=installation.server_name,
                server_version=installation.installed_version,
            )
            if cached_tool_count > 0:
                continue
            await refresh_tool_schemas_for_installation(
                session,
                installation=installation,
                server=server,
            )
        except (
            MCPGatewayUpstreamError,
            MCPServerInstallationFailedError,
            KubernetesRuntimeProviderError,
            ValueError,
        ) as exc:
            failure = AgentToolRefreshFailure(
                installation_id=installation.id,
                server_name=installation.server_name,
                server_version=installation.installed_version,
                config_name=installation.config_name,
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            failures.append(failure)
            logger.warning(
                "Failed to refresh wildcard MCP server tools; cached tools remain eligible.",
                extra={
                    "agent_id": str(agent_id),
                    "workspace_id": str(installation.workspace_id),
                    "mcp_server_name": installation.server_name,
                    "mcp_server_version": installation.installed_version,
                    "mcp_installation_id": str(installation.id),
                    "mcp_config_name": installation.config_name,
                    "error_type": failure.error_type,
                    "error": failure.error,
                },
            )
    return failures


async def record_agent_tool_refresh_failures(
    session: AsyncSession,
    *,
    agent_run_id: uuid.UUID,
    refresh_failures: list[AgentToolRefreshFailure],
) -> None:
    for failure in refresh_failures:
        await repository.append_agent_run_step(
            session,
            agent_run_id=agent_run_id,
            step_type="tool_discovery",
            status="failed",
            title=f"{failure.config_name} tools",
            payload={
                "installationId": str(failure.installation_id),
                "serverName": failure.server_name,
                "serverVersion": failure.server_version,
                "configName": failure.config_name,
                "errorType": failure.error_type,
                "error": sanitize_run_payload(failure.error),
            },
        )


def installed_agent_tools(
    rows: list[tuple[MCPServerToolSchema, MCPServerInstallation]],
) -> dict[str, AgentInstalledTool]:
    return {
        str(tool_schema.id): AgentInstalledTool(
            tool_schema=tool_schema,
            installation=installation,
        )
        for tool_schema, installation in rows
    }


async def stream_agent_chat(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentChatRequest,
    workspace_id: uuid.UUID | None = None,
    *,
    session_factory: AgentSessionFactory | None = None,
    trigger_type: str = "chat",
) -> AsyncGenerator[str, None]:
    agent, credential = await get_agent_model_for_run(
        session,
        user,
        organization_id,
        agent_id,
        workspace_id=workspace_id,
    )
    messages = provider_messages(payload.messages)
    if not messages:
        raise InvalidAgentScopeError("chat requires at least one user message")
    if workspace_id is None:
        raise InvalidAgentScopeError("agent chat requires a workspace")
    conversation = None
    conversation_id = conversation_id_from_payload(payload)
    if conversation_id is not None:
        conversation = await repository.get_workspace_conversation(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
        )
        if conversation is None or conversation.agent_id != agent.id:
            raise AgentNotFoundError("conversation not found")
    agent_run = await repository.create_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=conversation.id if conversation is not None else None,
        triggered_by_id=user.id,
        trigger_type=trigger_type,
    )
    latest_message = latest_user_message(payload.messages)
    await repository.append_agent_run_step(
        session,
        agent_run_id=agent_run.id,
        step_type="model_input",
        status="submitted",
        title="User message",
        payload={
            "message": sanitize_run_payload(text_from_chat_message(latest_message))
            if latest_message
            else "",
            "messageCount": len(payload.messages),
        },
    )
    if conversation is not None:
        await persist_chat_turn_user_message(session, conversation, payload, agent_run)
    installed_tools = installed_agent_tools(
        await repository.list_workspace_available_tools(session, workspace_id=workspace_id)
    )
    runtime_rows = await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    tools = agent_runtime_tools(runtime_rows)
    guardrail_filter = await filter_agent_runtime_tools_for_guardrails(
        session,
        tools,
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
        installed_tools=installed_tools,
    )
    latest_message = latest_user_message(payload.messages)
    denied_matches = denied_mcp_tool_matches(latest_message, guardrail_filter)
    if denied_matches:
        stream = stream_with_capability_diagnosis(
            guardrail_filter,
            preflight_blocked_tool_stream(guardrail_filter, denied_matches=denied_matches),
        )
        return persisted_agent_chat_stream(
            conversation,
            stream,
            agent_run,
            session_factory=session_factory,
        )

    tool_refresh_failures = await refresh_wildcard_agent_server_tools(session, agent.id)
    if tool_refresh_failures:
        await record_agent_tool_refresh_failures(
            session,
            agent_run_id=agent_run.id,
            refresh_failures=tool_refresh_failures,
        )
        logger.warning(
            "Continuing agent chat after MCP tool refresh failures; cached tools remain eligible.",
            extra={
                **agent_log_extra(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    user_id=user.id,
                    scope=agent.scope,
                ),
                "mcp_refresh_failure_count": len(tool_refresh_failures),
                "mcp_failed_installation_ids": [
                    str(failure.installation_id) for failure in tool_refresh_failures
                ],
            },
        )
    installed_tools = installed_agent_tools(
        await repository.list_workspace_available_tools(session, workspace_id=workspace_id)
    )
    runtime_rows = await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    tools = agent_runtime_tools(runtime_rows)
    guardrail_filter = await filter_agent_runtime_tools_for_guardrails(
        session,
        tools,
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
        installed_tools=installed_tools,
    )
    denied_matches = denied_mcp_tool_matches(latest_message, guardrail_filter)
    if denied_matches:
        stream = preflight_blocked_tool_stream(guardrail_filter, denied_matches=denied_matches)
    else:
        stream = run_agent_chat(
            agent,
            credential,
            AgentChatRequest(id=payload.id, messages=payload.messages),
            guardrail_filter,
            session_factory=session_factory,
            user=user,
            organization_id=organization_id,
            workspace_id=workspace_id,
            conversation=conversation,
            agent_run=agent_run,
        )
    stream = stream_with_capability_diagnosis(guardrail_filter, stream)
    return persisted_agent_chat_stream(
        conversation,
        stream,
        agent_run,
        session_factory=session_factory,
    )
