import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    enqueue_agent_tool_approval_resume as enqueue_agent_tool_approval_resume,
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
    InvalidAgentRunError,
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
    text_parts,
)
from app.modules.agents.models import (
    Agent,
    ConversationMessage,
    WorkspaceApprovedSkill,
    WorkspaceConversation,
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
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationResponse,
    AgentListResponse,
    AgentRead,
    AgentRunDeliveryRecipientRead,
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentSkillActivityRead,
    AgentSkillAgentRead,
    AgentSkillCatalogResponse,
    AgentSkillPermissionRead,
    AgentSkillRead,
    AgentSkillRecommendationRead,
    AgentSkillSearchResponse,
    AgentSkillSearchResultRead,
    AgentSkillUpdateRequest,
    AgentSkillUsageSummaryRead,
    AgentSkillWorkflowRead,
    WorkspaceAgentModelUpdate,
    WorkspaceApprovedSkillRead,
    WorkspaceSkillAgentAssignmentRequest,
    WorkspaceSkillApproveRequest,
)
from app.modules.agents.skills import (
    WARDN_FIND_SKILLS_DESCRIPTION,
    WARDN_FIND_SKILLS_ID,
    WARDN_FIND_SKILLS_NAME,
    WARDN_FIND_SKILLS_SOURCE,
    WARDN_FIND_SKILLS_SOURCE_URL,
    WARDN_FIND_SKILLS_URL,
    WARDN_GET_SKILL_TOOL_NAME,
    WARDN_SEARCH_SKILLS_TOOL_NAME,
    fetch_wardn_hub_skill_audit,
    find_skills_permission_summaries,
    get_wardn_hub_skill,
    normalize_agent_skill_ids,
    normalize_hub_skill_id,
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
from app.modules.chat_providers import repository as chat_provider_repository
from app.modules.chat_providers.models import ChatProviderEvent, ChatProviderThread
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
from app.modules.scheduled_tasks import repository as scheduled_task_repository
from app.modules.scheduled_tasks.models import (
    WorkspaceScheduledTaskDelivery,
    WorkspaceScheduledTaskRun,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)

AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS = 40_000
CHAT_COMMAND_COMPACT = "compact"
CHAT_COMMAND_NEW = "new"
CHAT_COMMANDS = {CHAT_COMMAND_COMPACT, CHAT_COMMAND_NEW}
CHAT_COMPACTION_PART_TYPE = "data-chat-compaction"
CHAT_COMPACTION_MAX_MESSAGES = 24
CHAT_COMPACTION_MAX_CHARS = 6_000
CHAT_COMPACTION_MESSAGE_MAX_CHARS = 800
QUICK_START_AGENT_NAME = "Workspace Assistant"
QUICK_START_AGENT_DESCRIPTION = "Default assistant for workspace chat."
QUICK_START_AGENT_INSTRUCTIONS = (
    "You are a workspace assistant. Use available tools when they help answer accurately. "
    "When no obvious workflow exists, search Wardn Hub skills for audited guidance, then use "
    "workspace tools through Wardn's tool search and execution flow. Ask before destructive "
    "actions."
)
CANCELABLE_AGENT_RUN_STATUSES = {"running", "submitted", "waiting_confirmation"}
CANCELED_RUN_ERROR = "Run canceled by user."
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


async def sync_workspace_agent_tools(
    session: AsyncSession,
    agent: Agent,
    workspace_id: uuid.UUID,
) -> None:
    if agent.workspace_id != workspace_id:
        return
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


sync_quick_start_agent_tools = sync_workspace_agent_tools


def skill_permission_reads() -> list[AgentSkillPermissionRead]:
    return [
        AgentSkillPermissionRead(**permission)
        for permission in find_skills_permission_summaries()
    ]


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def decoded_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip().startswith("{"):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def agent_skill_activity_summary(
    *,
    event_type: str,
    status: str,
    query: str,
    result_count: int | None,
    fetched_skill_id: str,
    audit_status: str,
    error: str,
) -> str:
    if error:
        return error
    if event_type == "selected":
        return "The model selected a Wardn skill capability through run_tool."
    if event_type == "search":
        count_text = (
            f"{result_count} result{'s' if result_count != 1 else ''}"
            if result_count is not None
            else "results pending"
        )
        return f'Searched Wardn Hub for "{query}" and returned {count_text}.'
    if event_type == "fetch":
        if audit_status:
            return f"Fetched {fetched_skill_id or 'a skill bundle'} with audit {audit_status}."
        return f"Fetched {fetched_skill_id or 'a skill bundle'}."
    return f"Recorded skill activity with status {status or 'unknown'}."


def agent_skill_activity_read(
    step,
    agent_run,
    agent: Agent,
) -> AgentSkillActivityRead | None:
    payload = dict_value(step.payload)
    details = dict_value(payload.get("details"))
    selection = dict_value(details.get("selection"))
    skill = dict_value(selection.get("skill")) if selection.get("toolType") == "skill" else {}
    event_type: str = "selected" if skill else "activity"

    if not skill:
        skill = dict_value(details.get("skill"))
        if not skill:
            return None
        raw_tool_name = string_value(skill.get("toolName"))
        if raw_tool_name == WARDN_SEARCH_SKILLS_TOOL_NAME:
            event_type = "search"
        elif raw_tool_name == WARDN_GET_SKILL_TOOL_NAME:
            event_type = "fetch"

    arguments = dict_value(payload.get("arguments"))
    result = decoded_json_object(payload.get("result"))
    audit = dict_value(result.get("audit"))
    query = string_value(arguments.get("query")) or string_value(result.get("query"))
    fetched_skill_id = (
        string_value(arguments.get("skillId"))
        or string_value(result.get("id"))
        or string_value(result.get("skillId"))
    )
    audit_status = (
        string_value(audit.get("status"))
        or string_value(result.get("auditStatus"))
        or string_value(result.get("audit_status"))
    )
    approved_result_count = int_or_none(result.get("approvedResultCount")) or 0
    approved = bool(result.get("approved")) or approved_result_count > 0
    temporary = bool(result.get("temporary", not approved))
    source = string_value(result.get("source")) or string_value(skill.get("source"))
    status = string_value(payload.get("status")) or step.status
    result_count = int_or_none(result.get("count"))
    tool_name = (
        string_value(selection.get("displayName"))
        or string_value(payload.get("toolName"))
        or step.title
    )
    summary = agent_skill_activity_summary(
        event_type=event_type,
        status=status,
        query=query,
        result_count=result_count,
        fetched_skill_id=fetched_skill_id,
        audit_status=audit_status,
        error=string_value(payload.get("error")),
    )

    return AgentSkillActivityRead(
        id=step.id,
        agent_run_id=agent_run.id,
        agent_id=agent.id,
        agent_name=agent.name,
        skill_id=string_value(skill.get("skillId")) or WARDN_FIND_SKILLS_ID,
        skill_name=string_value(skill.get("skillName")) or WARDN_FIND_SKILLS_NAME,
        tool_name=tool_name,
        event_type=event_type,
        status=status,
        query=query,
        result_count=result_count,
        fetched_skill_id=fetched_skill_id,
        audit_status=audit_status,
        source=source,
        approved=approved,
        temporary=temporary,
        summary=summary,
        created_at=step.created_at,
    )


def agent_skill_activity_reads(rows: list[tuple[Any, Any, Agent]]) -> list[AgentSkillActivityRead]:
    activities: list[AgentSkillActivityRead] = []
    seen_step_ids: set[uuid.UUID] = set()
    for step, agent_run, agent in rows:
        if step.id in seen_step_ids:
            continue
        activity = agent_skill_activity_read(step, agent_run, agent)
        if activity is None:
            continue
        seen_step_ids.add(step.id)
        activities.append(activity)
    return activities


def agent_skill_usage_by_agent(
    activities: list[AgentSkillActivityRead],
    *,
    now: datetime | None = None,
) -> dict[uuid.UUID, dict[str, Any]]:
    week_start = (now or datetime.now(UTC)) - timedelta(days=7)
    usage: dict[uuid.UUID, dict[str, Any]] = {}
    for activity in sorted(activities, key=lambda item: aware_utc(item.created_at), reverse=True):
        row = usage.setdefault(
            activity.agent_id,
            {
                "observed_skill_ids": set(),
                "calls_last_7d": 0,
                "searches_last_7d": 0,
                "fetches_last_7d": 0,
                "failures_last_7d": 0,
                "recent_run_id": None,
                "last_used_at": None,
            },
        )
        if row["recent_run_id"] is None:
            row["recent_run_id"] = activity.agent_run_id
        if row["last_used_at"] is None:
            row["last_used_at"] = activity.created_at
        if activity.skill_id:
            row["observed_skill_ids"].add(activity.skill_id)
        if activity.fetched_skill_id:
            row["observed_skill_ids"].add(activity.fetched_skill_id)
        if aware_utc(activity.created_at) < week_start:
            continue
        row["calls_last_7d"] += 1
        if activity.event_type == "search":
            row["searches_last_7d"] += 1
        if activity.event_type == "fetch":
            row["fetches_last_7d"] += 1
        if activity.status in {"failed", "blocked"}:
            row["failures_last_7d"] += 1
    return usage


def agent_skill_usage_by_skill(
    activities: list[AgentSkillActivityRead],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    week_start = (now or datetime.now(UTC)) - timedelta(days=7)
    usage: dict[str, dict[str, Any]] = {}
    for activity in sorted(activities, key=lambda item: aware_utc(item.created_at), reverse=True):
        skill_ids = [activity.fetched_skill_id or activity.skill_id]
        for skill_id in [value for value in skill_ids if value]:
            row = usage.setdefault(
                skill_id,
                {
                    "usage_count_last_7d": 0,
                    "last_used_at": None,
                },
            )
            if row["last_used_at"] is None:
                row["last_used_at"] = activity.created_at
            if aware_utc(activity.created_at) < week_start:
                continue
            if activity.event_type in {"fetch", "selected"}:
                row["usage_count_last_7d"] += 1
    return usage


def workspace_skill_context(skill: WorkspaceApprovedSkill) -> dict[str, Any]:
    metadata = skill.metadata_json if isinstance(skill.metadata_json, dict) else {}
    return {
        "workspaceSkillId": str(skill.id),
        "skillId": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "url": skill.url,
        "source": skill.source,
        "sourceUrl": skill.source_url,
        "sourceOwner": skill.source_owner,
        "sourceName": skill.source_name,
        "auditStatus": skill.audit_status,
        "auditScore": skill.audit_score,
        "auditRank": skill.audit_rank,
        "contentHash": skill.content_hash,
        "isOfficial": bool(metadata.get("isOfficial")),
        "installs": int(metadata.get("installs") or 0),
    }


def ensure_find_skills_gateway_enabled(agents: list[Agent]) -> None:
    for agent in agents:
        skill_ids = normalize_agent_skill_ids(agent.skill_ids or [])
        if WARDN_FIND_SKILLS_ID not in skill_ids:
            agent.skill_ids = [*skill_ids, WARDN_FIND_SKILLS_ID]


def workspace_approved_skill_read(
    skill: WorkspaceApprovedSkill,
    *,
    assigned_agents: list[Agent] | None = None,
    usage: dict[str, Any] | None = None,
) -> WorkspaceApprovedSkillRead:
    assigned_agents = assigned_agents or []
    usage = usage or {}
    return WorkspaceApprovedSkillRead(
        id=skill.id,
        skill_id=skill.skill_id,
        name=skill.name,
        description=skill.description,
        url=skill.url,
        source=skill.source,
        source_url=skill.source_url,
        source_owner=skill.source_owner,
        source_name=skill.source_name,
        audit_status=skill.audit_status,
        audit_score=skill.audit_score,
        audit_rank=skill.audit_rank,
        audit_summary=skill.audit_summary,
        content_hash=skill.content_hash,
        status=skill.status,
        assigned_agent_ids=[agent.id for agent in assigned_agents],
        assigned_agent_names=[agent.name for agent in assigned_agents],
        last_used_at=usage.get("last_used_at"),
        usage_count_last_7d=int(usage.get("usage_count_last_7d") or 0),
        approved_by_id=skill.approved_by_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def agent_skill_usage_summary(
    *,
    agents: list[Agent],
    active_skills: int,
    approved_skills: list[WorkspaceApprovedSkill] | None = None,
    assignments: list[tuple[WorkspaceApprovedSkill, Any, Agent]] | None = None,
    activities: list[AgentSkillActivityRead],
    now: datetime | None = None,
) -> AgentSkillUsageSummaryRead:
    week_start = (now or datetime.now(UTC)) - timedelta(days=7)
    recent = [
        activity for activity in activities if aware_utc(activity.created_at) >= week_start
    ]
    last_activity = max(
        activities,
        key=lambda activity: aware_utc(activity.created_at),
        default=None,
    )
    enabled_agents = sum(
        1
        for agent in agents
        if WARDN_FIND_SKILLS_ID in normalize_agent_skill_ids(agent.skill_ids or [])
    )
    if approved_skills:
        enabled_agents = len(agents)
    return AgentSkillUsageSummaryRead(
        active_skills=active_skills,
        approved_skills=len(approved_skills or []),
        assigned_approved_skills=len(assignments or []),
        total_agents=len(agents),
        enabled_agents=enabled_agents,
        skill_events_last_7d=len(recent),
        skill_runs_last_7d=len({activity.agent_run_id for activity in recent}),
        searches_last_7d=sum(1 for activity in recent if activity.event_type == "search"),
        fetches_last_7d=sum(1 for activity in recent if activity.event_type == "fetch"),
        failures_last_7d=sum(
            1 for activity in recent if activity.status in {"failed", "blocked"}
        ),
        last_used_at=last_activity.created_at if last_activity else None,
    )


def agent_skill_agent_read(
    agent: Agent,
    usage: dict[str, Any] | None = None,
    assigned_skills: list[WorkspaceApprovedSkill] | None = None,
) -> AgentSkillAgentRead:
    usage = usage or {}
    assigned_skills = assigned_skills or []
    enabled_skill_ids = normalize_agent_skill_ids(agent.skill_ids or [])
    return AgentSkillAgentRead(
        id=agent.id,
        name=agent.name,
        enabled_skill_ids=enabled_skill_ids,
        assigned_approved_skill_ids=[skill.skill_id for skill in assigned_skills],
        assigned_workspace_skill_ids=[skill.id for skill in assigned_skills],
        available_skill_count=len(enabled_skill_ids) + len(assigned_skills),
        observed_skill_ids=sorted(usage.get("observed_skill_ids") or []),
        calls_last_7d=int(usage.get("calls_last_7d") or 0),
        searches_last_7d=int(usage.get("searches_last_7d") or 0),
        fetches_last_7d=int(usage.get("fetches_last_7d") or 0),
        failures_last_7d=int(usage.get("failures_last_7d") or 0),
        recent_run_id=usage.get("recent_run_id"),
        last_used_at=usage.get("last_used_at"),
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
    skill_step_rows = await repository.list_recent_workspace_agent_run_steps(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=250,
    )
    recent_activity = agent_skill_activity_reads(skill_step_rows)
    usage_by_agent = agent_skill_usage_by_agent(recent_activity)
    usage_by_skill = agent_skill_usage_by_skill(recent_activity)
    approved_skills = await repository.list_workspace_approved_skills(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    assignments = await repository.list_workspace_approved_skill_assignments(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    audit_metadata = await find_skills_audit_metadata()
    skills = [find_skills_read(agents=agents, audit_metadata=audit_metadata)]
    return AgentSkillCatalogResponse(
        skills=skills,
        library=[
            workspace_approved_skill_read(
                skill,
                assigned_agents=agents,
                usage=usage_by_skill.get(skill.skill_id),
            )
            for skill in approved_skills
        ],
        agents=[
            agent_skill_agent_read(
                agent,
                usage=usage_by_agent.get(agent.id),
                assigned_skills=approved_skills,
            )
            for agent in agents
        ],
        recommendations=workspace_skill_recommendations(installations),
        guided_workflows=workspace_guided_skill_workflows(),
        usage_summary=agent_skill_usage_summary(
            agents=agents,
            active_skills=sum(1 for skill in skills if skill.installed),
            approved_skills=approved_skills,
            assignments=assignments,
            activities=recent_activity,
        ),
        recent_activity=recent_activity[:50],
    )


def approved_skill_model_fields(
    *,
    payload: dict[str, Any],
    skill_id: str,
    user_id: uuid.UUID | None,
) -> dict[str, Any]:
    audit = skill_audit_summary(payload.get("audit")) or {}
    parts = skill_id.split("/")
    source_owner = string_value(payload.get("sourceOwner")) or (parts[0] if len(parts) > 0 else "")
    source_name = string_value(payload.get("sourceName")) or (parts[1] if len(parts) > 1 else "")
    source = string_value(payload.get("source")) or (
        f"{source_owner}/{source_name}" if source_owner and source_name else ""
    )
    return {
        "approved_by_id": user_id,
        "skill_id": skill_id,
        "name": string_value(payload.get("name")) or skill_id.rsplit("/", 1)[-1],
        "description": string_value(payload.get("description")),
        "url": string_value(payload.get("url")) or f"https://hub.wardnai.dev/skills/{skill_id}",
        "source": source,
        "source_url": string_value(payload.get("sourceUrl")),
        "source_owner": source_owner,
        "source_name": source_name,
        "audit_status": string_value(audit.get("status")) or "unknown",
        "audit_score": audit.get("score") if isinstance(audit.get("score"), int) else None,
        "audit_rank": string_value(audit.get("rank")),
        "audit_summary": string_value(audit.get("summary")),
        "content_hash": string_value(payload.get("hash")),
        "status": "active",
        "metadata_json": {
            "bundleFormatVersion": payload.get("bundleFormatVersion"),
            "files": payload.get("files") or [],
            "isOfficial": bool(payload.get("isOfficial")),
            "resolutionIssues": payload.get("resolutionIssues") or [],
            "resolutionStatus": payload.get("resolutionStatus"),
            "sourceEntrypoint": payload.get("sourceEntrypoint"),
        },
    }


async def approve_workspace_skill(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: WorkspaceSkillApproveRequest,
) -> WorkspaceApprovedSkillRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    try:
        skill_id = normalize_hub_skill_id(payload.skill_id)
        hub_payload = await get_wardn_hub_skill({"skillId": skill_id})
    except ValueError as exc:
        raise InvalidAgentScopeError(str(exc)) from exc
    audit = skill_audit_summary(hub_payload.get("audit"))
    if hub_payload.get("rejected") or rejecting_audit_summary(audit):
        raise InvalidAgentScopeError(
            "Skill bundle was not approved because its audit status is unsafe."
        )
    existing = await repository.get_workspace_approved_skill_by_skill_id(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        skill_id=skill_id,
    )
    fields = approved_skill_model_fields(
        payload=hub_payload,
        skill_id=skill_id,
        user_id=user.id,
    )
    if existing is None:
        existing = WorkspaceApprovedSkill(
            organization_id=organization_id,
            workspace_id=workspace_id,
            **fields,
        )
        session.add(existing)
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
    await session.flush()
    agents = await repository.list_active_workspace_agents(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    ensure_find_skills_gateway_enabled(agents)
    await session.flush()
    await repository.replace_workspace_approved_skill_assignments(
        session,
        workspace_skill_id=existing.id,
        agents=agents,
    )
    await session.refresh(existing)
    return workspace_approved_skill_read(existing, assigned_agents=agents)


async def assign_workspace_skill_agents(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    workspace_skill_id: uuid.UUID,
    payload: WorkspaceSkillAgentAssignmentRequest,
) -> WorkspaceApprovedSkillRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    workspace_skill = await repository.get_workspace_approved_skill(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        workspace_skill_id=workspace_skill_id,
    )
    if workspace_skill is None:
        raise AgentNotFoundError("workspace skill not found")
    agent_ids = list(dict.fromkeys(payload.agent_ids))
    agents: list[Agent] = []
    for agent_id in agent_ids:
        agent = await repository.get_agent(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if agent is None:
            raise AgentNotFoundError("agent not found")
        agents.append(agent)
    ensure_find_skills_gateway_enabled(agents)
    await session.flush()
    await repository.replace_workspace_approved_skill_assignments(
        session,
        workspace_skill_id=workspace_skill.id,
        agents=agents,
    )
    await session.refresh(workspace_skill)
    return workspace_approved_skill_read(workspace_skill, assigned_agents=agents)


async def remove_workspace_skill(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    workspace_skill_id: uuid.UUID,
) -> None:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    workspace_skill = await repository.get_workspace_approved_skill(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        workspace_skill_id=workspace_skill_id,
    )
    if workspace_skill is None:
        raise AgentNotFoundError("workspace skill not found")
    await repository.delete_workspace_approved_skill(session, workspace_skill=workspace_skill)


async def update_agent_skills(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentSkillUpdateRequest,
) -> AgentSkillAgentRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    try:
        skill_ids = normalize_agent_skill_ids(payload.skill_ids)
    except ValueError as exc:
        raise InvalidAgentScopeError(str(exc)) from exc
    agent.skill_ids = skill_ids
    await session.flush()
    await session.refresh(agent)
    return agent_skill_agent_read(agent)


def skill_search_result_read(
    item: dict[str, Any],
    *,
    approved_by_skill_id: dict[str, WorkspaceApprovedSkill] | None = None,
) -> AgentSkillSearchResultRead:
    approved_by_skill_id = approved_by_skill_id or {}
    skill_id = str(item.get("id") or "")
    approved_skill = approved_by_skill_id.get(skill_id)
    approved = approved_skill is not None or bool(item.get("approved"))
    return AgentSkillSearchResultRead(
        id=skill_id,
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
        approved=approved,
        workspace_skill_id=approved_skill.id if approved_skill else None,
        installed=approved or item.get("id") == WARDN_FIND_SKILLS_ID,
        temporary=not approved and item.get("id") != WARDN_FIND_SKILLS_ID,
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
    approved_skills = await repository.list_workspace_approved_skills(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    approved_by_skill_id = {skill.skill_id: skill for skill in approved_skills}
    try:
        payload = await search_wardn_hub_skills({"query": query, "limit": limit})
    except ValueError as exc:
        raise InvalidAgentScopeError(str(exc)) from exc
    return AgentSkillSearchResponse(
        query=str(payload.get("query") or query),
        count=int(payload.get("count") or 0),
        results=[
            skill_search_result_read(item, approved_by_skill_id=approved_by_skill_id)
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
    agent = await ensure_workspace_assistant_agent(
        session,
        user,
        organization_id,
        workspace_id,
    )
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


async def ensure_workspace_assistant_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Agent:
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
        if changed:
            await session.flush()
            await session.refresh(agent)
    await sync_workspace_agent_tools(session, agent, workspace_id)
    return agent


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
        agent.is_active = True
    await session.flush()
    await session.refresh(agent)
    await sync_workspace_agent_tools(session, agent, workspace_id)
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


def agent_run_can_cancel(agent_run) -> bool:
    return agent_run.status in CANCELABLE_AGENT_RUN_STATUSES


def replayable_step_message(steps) -> str:
    for step in reversed(steps):
        if step.step_type != "model_input":
            continue
        payload = step.payload if isinstance(step.payload, dict) else {}
        message = str(payload.get("message") or "").strip()
        if message:
            return message
    return ""


def agent_run_can_rerun(agent_run, steps: list | None = None) -> bool:
    if agent_run.conversation_id is not None:
        return True
    return bool(replayable_step_message(steps or []))


def scheduled_delivery_recipient(
    delivery: WorkspaceScheduledTaskDelivery,
    task_run: WorkspaceScheduledTaskRun,
) -> AgentRunDeliveryRecipientRead:
    summary = task_run.delivery_summary if isinstance(task_run.delivery_summary, dict) else {}
    route_type = "Built-in chat" if delivery.route_type == "chat" else "Chat provider"
    return AgentRunDeliveryRecipientRead(
        id=delivery.id,
        source="scheduled_task_delivery",
        routeType=route_type,
        provider=delivery.provider,
        connectionId=delivery.connection_id,
        externalThreadId=delivery.external_thread_id,
        displayName=delivery.display_name
        or ("Built-in chat" if delivery.route_type == "chat" else delivery.external_thread_id),
        status=delivery.status,
        outputKind=str(summary.get("outputKind") or ""),
        error=delivery.error,
        deliveredAt=delivery.delivered_at,
        createdAt=delivery.created_at,
    )


def provider_event_recipient(
    event: ChatProviderEvent,
    thread: ChatProviderThread | None,
) -> AgentRunDeliveryRecipientRead:
    payload = event.payload if isinstance(event.payload, dict) else {}
    provider_payload = payload.get(event.provider)
    provider_delivered = isinstance(provider_payload, dict)
    is_approval_request = event.event_type == "approval.request" or bool(
        payload.get("approvalRequest")
    )
    route_type = str(payload.get("routeType") or "").strip()
    if route_type == "none":
        display_route_type = "No external approval route"
    elif route_type == "chat":
        display_route_type = "Wardn approval route"
    elif route_type == "workspace_member":
        display_route_type = "Wardn approver"
    elif is_approval_request:
        display_route_type = "Approval route"
    else:
        display_route_type = "Chat provider"
    status = event.status
    if is_approval_request and not provider_delivered and status == "processed":
        status = "not_configured"
    return AgentRunDeliveryRecipientRead(
        id=event.id,
        source="chat_provider_reply",
        routeType=display_route_type,
        provider=(
            event.provider
            if provider_delivered or payload.get("externalDelivery") is not False
            else ""
        ),
        connectionId=event.connection_id,
        externalThreadId=(
            thread.external_thread_id
            if provider_delivered and thread is not None
            else str(payload.get("externalThreadId") or "")
        ),
        displayName=(
            thread.external_user_display_name
            if provider_delivered and thread is not None and thread.external_user_display_name
            else str(payload.get("displayName") or "")
        ),
        status=status,
        outputKind="approval" if is_approval_request else "assistant",
        error=event.error,
        deliveredAt=event.processed_at if provider_delivered else None,
        createdAt=event.created_at,
    )


async def agent_run_delivery_recipients(
    session: AsyncSession,
    agent_run,
) -> list[AgentRunDeliveryRecipientRead]:
    recipients = [
        scheduled_delivery_recipient(delivery, task_run)
        for delivery, task_run in await scheduled_task_repository.list_deliveries_for_agent_run(
            session,
            organization_id=agent_run.organization_id,
            workspace_id=agent_run.workspace_id,
            agent_run_id=agent_run.id,
        )
    ]
    provider_events = await chat_provider_repository.list_outbound_events_for_agent_run(
        session,
        organization_id=agent_run.organization_id,
        workspace_id=agent_run.workspace_id,
        agent_run_id=agent_run.id,
    )
    for event, thread in provider_events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("scheduledTaskRunId"):
            continue
        recipients.append(provider_event_recipient(event, thread))
    return recipients


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
                can_cancel=agent_run_can_cancel(agent_run),
                can_rerun=True,
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
            can_cancel=agent_run_can_cancel(agent_run),
            can_rerun=agent_run_can_rerun(agent_run, steps),
            trace_id=trace_id,
            span_id=span_id,
            trigger_type=response_trigger_type(agent_run, provider_triggers),
        ),
        steps=[agent_run_step_response(step) for step in steps],
        deliveryRecipients=await agent_run_delivery_recipients(session, agent_run),
    )


async def cancel_workspace_agent_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> AgentRunDetailResponse:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    agent_run = await repository.get_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
        for_update=True,
    )
    if agent_run is None:
        raise AgentNotFoundError("agent run not found")
    if not agent_run_can_cancel(agent_run):
        raise InvalidAgentRunError("only running, submitted, or waiting runs can be canceled")
    now = datetime.now(UTC)
    approvals = await repository.list_active_tool_approvals_for_agent_run(
        session,
        agent_run_id=agent_run.id,
    )
    for approval in approvals:
        approval.status = "denied" if approval.status == "pending" else "failed"
        approval.error = CANCELED_RUN_ERROR
        approval.decided_by_id = user.id
        if approval.conversation_id is not None:
            await repository.update_conversation_tool_activity(
                session,
                conversation_id=approval.conversation_id,
                approval_id=approval.id,
                data_update={"status": approval.status, "error": approval.error},
            )
    await repository.append_agent_run_step(
        session,
        agent_run_id=agent_run.id,
        step_type="cancellation",
        status="canceled",
        title="Run canceled",
        payload={"message": CANCELED_RUN_ERROR, "canceledById": str(user.id)},
    )
    await repository.finish_agent_run(
        session,
        agent_run,
        status="canceled",
        error=CANCELED_RUN_ERROR,
        now=now,
    )
    return await get_workspace_agent_run(
        session,
        user,
        organization_id,
        workspace_id,
        agent_run.id,
    )


async def agent_run_replay_message(
    session: AsyncSession,
    agent_run,
    steps: list | None = None,
) -> AgentChatMessage | None:
    if agent_run.conversation_id is not None:
        messages = await repository.list_conversation_messages(
            session,
            conversation_id=agent_run.conversation_id,
        )
        for message in reversed(messages):
            if message.agent_run_id == agent_run.id and message.role == "user":
                content = message.content.strip()
                if content:
                    return AgentChatMessage(role="user", parts=message.parts or text_parts(content))
    message = replayable_step_message(steps or [])
    if message:
        return AgentChatMessage(role="user", parts=text_parts(message))
    return None


async def deliver_provider_rerun_reply(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> None:
    thread_connection = await chat_provider_repository.get_thread_connection_for_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    if thread_connection is None:
        return
    thread, connection = thread_connection
    if not connection.is_active:
        return
    from app.modules.chat_providers import service as chat_provider_service

    assistant_message = await chat_provider_service.latest_assistant_message(
        session,
        conversation_id,
    )
    if await chat_provider_service.assistant_message_run_canceled(
        session,
        connection,
        assistant_message,
    ):
        return
    reply_text = assistant_message.content.strip() if assistant_message is not None else ""
    if not reply_text:
        reply_text = await chat_provider_service.route_pending_approval_request_reply(
            session,
            connection,
            conversation_id=conversation_id,
            initiating_event_id=thread.last_external_message_id or f"rerun:{agent_run_id}",
        )
    elif chat_provider_service.reply_exposes_wardn_approval_url(reply_text):
        reply_text = (
            await chat_provider_service.route_pending_approval_request_reply(
                session,
                connection,
                conversation_id=conversation_id,
                initiating_event_id=thread.last_external_message_id or f"rerun:{agent_run_id}",
            )
            or chat_provider_service.PROVIDER_APPROVAL_PENDING_UNDELIVERED_REPLY
        )
    if not reply_text:
        reply_text = chat_provider_service.PROVIDER_ASSISTANT_EMPTY_REPLY
    try:
        outbound_payload = await chat_provider_service.send_provider_text_message(
            session,
            connection,
            external_thread_id=thread.external_thread_id,
            text=reply_text,
            reply_to_message_id=thread.last_external_message_id,
        )
    except chat_provider_service.ChatProviderDeliveryError as exc:
        await chat_provider_service.record_provider_text_delivery_failure(
            session,
            connection,
            thread=thread,
            conversation_id=conversation_id,
            external_event_id=f"rerun:{agent_run_id}:{thread.id}:failed",
            text=reply_text,
            error=str(exc),
            agent_run_id=agent_run_id,
        )
        await session.flush()
        return
    outbound_message_id = chat_provider_service.provider_response_message_id(
        connection,
        outbound_payload,
    )
    session.add(
        ChatProviderEvent(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connection_id=connection.id,
            thread_id=thread.id,
            conversation_id=conversation_id,
            provider=connection.provider,
            external_event_id=outbound_message_id or f"rerun:{agent_run_id}:{thread.id}",
            direction="outbound",
            event_type="message.text",
            status="sent",
            payload={connection.provider: outbound_payload, "agentRunId": str(agent_run_id)},
            processed_at=datetime.now(UTC),
        )
    )
    await session.flush()


async def rerun_workspace_agent_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> AgentRunDetailResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    original_run = await repository.get_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
    )
    if original_run is None:
        raise AgentNotFoundError("agent run not found")
    steps = await repository.list_agent_run_steps(session, agent_run_id=original_run.id)
    replay_message = await agent_run_replay_message(session, original_run, steps)
    if replay_message is None:
        raise InvalidAgentRunError("agent run does not have a replayable user message")

    created_agent_run_id: uuid.UUID | None = None

    def capture_agent_run_id(next_agent_run_id: uuid.UUID) -> None:
        nonlocal created_agent_run_id
        created_agent_run_id = next_agent_run_id

    stream = await stream_agent_chat(
        session,
        user,
        organization_id,
        original_run.agent_id,
        AgentChatRequest(
            id=str(original_run.conversation_id) if original_run.conversation_id else "",
            messages=[replay_message],
        ),
        workspace_id=workspace_id,
        trigger_type=original_run.trigger_type,
        on_agent_run_created=capture_agent_run_id,
    )
    await session.commit()
    async for _chunk in stream:
        pass
    if created_agent_run_id is None:
        raise InvalidAgentRunError("agent run could not be rerun")
    if original_run.trigger_type in {"telegram", "whatsapp", "whatsapp_local"}:
        if original_run.conversation_id is not None:
            await deliver_provider_rerun_reply(
                session,
                organization_id=organization_id,
                workspace_id=workspace_id,
                conversation_id=original_run.conversation_id,
                agent_run_id=created_agent_run_id,
            )
    return await get_workspace_agent_run(
        session,
        user,
        organization_id,
        workspace_id,
        created_agent_run_id,
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


def chat_messages_match(left: AgentChatMessage, right: AgentChatMessage) -> bool:
    return left.role == right.role and text_from_chat_message(left) == text_from_chat_message(right)


def chat_command_from_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    token = stripped.split(maxsplit=1)[0][1:].casefold()
    return token if token in CHAT_COMMANDS else None


def chat_command_from_message(message: AgentChatMessage | None) -> str | None:
    if message is None:
        return None
    return chat_command_from_text(text_from_chat_message(message))


def conversation_message_has_part(message: ConversationMessage, part_type: str) -> bool:
    return any(part.get("type") == part_type for part in message.parts or [])


def is_compaction_message(message: ConversationMessage) -> bool:
    return (
        message.role == "system"
        and conversation_message_has_part(message, CHAT_COMPACTION_PART_TYPE)
    )


def latest_compaction_index(messages: list[ConversationMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if is_compaction_message(messages[index]):
            return index
    return None


def compaction_message_to_chat_message(message: ConversationMessage) -> AgentChatMessage:
    return AgentChatMessage(
        role="assistant",
        parts=text_parts(f"Earlier conversation summary:\n{message.content}"),
    )


def incoming_chat_message_tail(
    persisted_messages: list[AgentChatMessage],
    incoming_messages: list[AgentChatMessage],
) -> list[AgentChatMessage]:
    if not persisted_messages:
        return incoming_messages
    max_overlap = min(len(persisted_messages), len(incoming_messages))
    for overlap in range(max_overlap, 0, -1):
        persisted_anchor = persisted_messages[-overlap:]
        for start in range(len(incoming_messages) - overlap, -1, -1):
            incoming_slice = incoming_messages[start : start + overlap]
            if all(
                chat_messages_match(persisted, incoming)
                for persisted, incoming in zip(
                    persisted_anchor,
                    incoming_slice,
                    strict=True,
                )
            ):
                return incoming_messages[start + overlap :]
    return incoming_messages


def conversation_chat_context_messages(
    persisted_messages: list[ConversationMessage],
    incoming_messages: list[AgentChatMessage],
) -> tuple[list[AgentChatMessage], list[AgentChatMessage]]:
    compaction_index = latest_compaction_index(persisted_messages)
    compacted_context_messages: list[AgentChatMessage] = []
    persisted_visible_messages: list[AgentChatMessage] = []
    replay_messages = (
        persisted_messages[compaction_index:]
        if compaction_index is not None
        else persisted_messages
    )
    for message in replay_messages:
        if is_compaction_message(message):
            compacted_context_messages.append(compaction_message_to_chat_message(message))
        elif message.role in {"user", "assistant"}:
            persisted_visible_messages.append(conversation_message_to_chat_message(message))
    incoming_chat_messages = [
        message for message in incoming_messages if message.role in {"user", "assistant"}
    ]
    incoming_tail = incoming_chat_message_tail(
        persisted_visible_messages,
        incoming_chat_messages,
    )
    return [*compacted_context_messages, *persisted_visible_messages, *incoming_tail], incoming_tail


def compact_text(value: str, *, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3].rstrip()}..."


def compactable_conversation_messages(
    messages: list[ConversationMessage],
) -> list[ConversationMessage]:
    compaction_index = latest_compaction_index(messages)
    candidates = (
        messages[compaction_index:]
        if compaction_index is not None
        else messages
    )
    return [
        message
        for message in candidates
        if is_compaction_message(message)
        or (
            message.role in {"user", "assistant"}
            and chat_command_from_text(message.content) != CHAT_COMMAND_COMPACT
        )
    ]


def conversation_message_compaction_line(message: ConversationMessage) -> str:
    if is_compaction_message(message):
        label = "Previous summary"
    elif message.role == "user":
        label = "User"
    else:
        label = "Assistant"
    content = compact_text(message.content, max_chars=CHAT_COMPACTION_MESSAGE_MAX_CHARS)
    return f"- {label}: {content}"


def conversation_compaction_summary(messages: list[ConversationMessage]) -> str:
    compactable_messages = compactable_conversation_messages(messages)
    if len(compactable_messages) < 2:
        return ""
    selected_messages = compactable_messages[-CHAT_COMPACTION_MAX_MESSAGES:]
    omitted_count = max(len(compactable_messages) - len(selected_messages), 0)
    lines = [
        "Compacted conversation context. Use this as background for future replies.",
        f"Messages compacted: {len(compactable_messages)}.",
    ]
    if omitted_count:
        lines.append(f"Older messages omitted from this compacted snapshot: {omitted_count}.")
    lines.append("Recent compacted transcript:")
    lines.extend(conversation_message_compaction_line(message) for message in selected_messages)
    summary = "\n".join(lines)
    if len(summary) <= CHAT_COMPACTION_MAX_CHARS:
        return summary
    return summary[-CHAT_COMPACTION_MAX_CHARS:].lstrip()


async def compact_workspace_conversation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> ConversationMessage | None:
    await require_workspace_member(session, user, organization_id, workspace_id)
    conversation = await repository.get_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise AgentNotFoundError("conversation not found")
    messages = await repository.list_conversation_messages(
        session,
        conversation_id=conversation.id,
    )
    summary = conversation_compaction_summary(messages)
    if not summary:
        return None
    return await repository.append_conversation_message(
        session,
        conversation_id=conversation.id,
        role="system",
        content=summary,
        parts=[
            {"type": CHAT_COMPACTION_PART_TYPE, "data": {"messageCount": len(messages)}},
            {"type": "text", "text": summary},
        ],
    )


async def chat_command_text_stream(text: str) -> AsyncGenerator[AgentChatTextEvent, None]:
    yield AgentChatTextEvent(text=text)


async def create_workspace_agent_conversation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent: Agent,
    *,
    title: str = "New chat",
) -> WorkspaceConversation:
    await require_workspace_member(session, user, organization_id, workspace_id)
    await require_workspace_conversation_create_limit(session, user, organization_id, workspace_id)
    return await repository.create_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        created_by_id=user.id,
        title=title,
    )


async def new_chat_command_stream(
    conversation: WorkspaceConversation,
) -> AsyncGenerator[str, None]:
    message_id = str(uuid.uuid4())
    text_id = f"text-{message_id}"
    text = "Started a new chat."
    yield ui_message_sse_chunk({"type": "start", "messageId": message_id})
    yield ui_message_sse_chunk(
        {
            "type": "data-chat-command",
            "id": f"command-{message_id}",
            "data": {
                "command": CHAT_COMMAND_NEW,
                "conversationId": str(conversation.id),
            },
        }
    )
    yield ui_message_sse_chunk({"type": "text-start", "id": text_id})
    yield ui_message_sse_chunk({"type": "text-delta", "id": text_id, "delta": text})
    yield ui_message_sse_chunk({"type": "text-end", "id": text_id})
    yield ui_message_sse_chunk({"type": "finish", "finishReason": "stop"})


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
    on_agent_run_created: Callable[[uuid.UUID], None] | None = None,
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
    latest_message = latest_user_message(payload.messages)
    command = chat_command_from_message(latest_message)
    if command == CHAT_COMMAND_NEW:
        new_conversation = await create_workspace_agent_conversation(
            session,
            user,
            organization_id,
            workspace_id,
            agent,
        )
        return new_chat_command_stream(new_conversation)
    conversation = None
    chat_messages = payload.messages
    new_chat_messages = payload.messages
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
        persisted_messages = await repository.list_conversation_messages(
            session,
            conversation_id=conversation.id,
        )
        chat_messages, new_chat_messages = conversation_chat_context_messages(
            persisted_messages,
            payload.messages,
        )
    agent_run = await repository.create_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=conversation.id if conversation is not None else None,
        triggered_by_id=user.id,
        trigger_type=trigger_type,
    )
    if on_agent_run_created is not None:
        on_agent_run_created(agent_run.id)
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
            "messageCount": len(chat_messages),
        },
    )
    new_latest_message = latest_user_message(new_chat_messages)
    if conversation is not None and new_latest_message is not None:
        await persist_chat_turn_user_message(
            session,
            conversation,
            AgentChatRequest(id=payload.id, messages=new_chat_messages),
            agent_run,
        )
    if command == CHAT_COMMAND_COMPACT:
        if conversation is None:
            text = "There is no active conversation to compact yet."
        else:
            compacted_message = await compact_workspace_conversation(
                session,
                user,
                organization_id,
                workspace_id,
                conversation.id,
            )
            text = (
                "Compacted this chat. Future replies will use the compacted context "
                "plus new messages."
                if compacted_message is not None
                else "There is not enough conversation to compact yet."
            )
        return persisted_agent_chat_stream(
            conversation,
            chat_command_text_stream(text),
            agent_run,
            session_factory=session_factory,
        )
    await sync_workspace_agent_tools(session, agent, workspace_id)
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
            AgentChatRequest(id=payload.id, messages=chat_messages),
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
