from app.db.domain_types import AgentScope, MCPOperationJobStatus, MembershipRole
from app.modules.agents.models import Agent, ConversationMessage
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPOperationJob,
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_runtime.models import MCPRuntimeEvent, MCPRuntimeSession, MCPToolInvocation
from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)


def constraint_names(model: type) -> set[str]:
    return {constraint.name for constraint in model.__table__.constraints if constraint.name}


def foreign_key_delete_actions(model: type) -> dict[str, str | None]:
    return {
        constraint.name: constraint.ondelete
        for constraint in model.__table__.foreign_key_constraints
        if constraint.name
    }


def index_names(model: type) -> set[str]:
    return {index.name for index in model.__table__.indexes if index.name}


def test_scoped_domain_models_declare_database_invariants() -> None:
    assert "ck_organizations_status" in constraint_names(Organization)
    assert "ck_organization_memberships_role" in constraint_names(OrganizationMembership)
    assert "ck_workspaces_status" in constraint_names(Workspace)
    assert "ck_workspace_memberships_role" in constraint_names(WorkspaceMembership)
    assert {"ck_agents_scope", "ck_agents_scope_workspace"} <= constraint_names(Agent)
    assert "ck_conversation_messages_role" in constraint_names(ConversationMessage)
    assert {
        "ck_llm_provider_credentials_visibility",
        "ck_llm_provider_credentials_visibility_scope",
        "ck_llm_provider_credentials_auth_method",
        "ck_llm_provider_credentials_auth_material",
    } <= constraint_names(LLMProviderCredential)
    assert {
        "fk_llm_provider_credentials_api_key_secret_handle": "RESTRICT",
        "fk_llm_provider_credentials_oauth_access_secret_handle": "RESTRICT",
        "fk_llm_provider_credentials_oauth_refresh_secret_handle": "RESTRICT",
    }.items() <= foreign_key_delete_actions(LLMProviderCredential).items()


def test_registry_models_declare_database_invariants() -> None:
    assert "ck_mcp_server_versions_status" in constraint_names(MCPServerVersion)
    assert {
        "ck_mcp_catalog_sources_provider",
        "ck_mcp_catalog_sources_sync_mode",
    } <= constraint_names(MCPCatalogSource)
    assert "ck_mcp_server_installations_status" in constraint_names(MCPServerInstallation)
    assert {
        "ck_mcp_operation_jobs_status",
        "ck_mcp_operation_jobs_cleanup_status",
        "ck_mcp_operation_jobs_progress",
        "ck_mcp_operation_jobs_attempts",
    } <= constraint_names(MCPOperationJob)


def test_runtime_models_declare_retention_indexes() -> None:
    assert {
        "ix_mcp_runtime_events_retention",
        "ix_mcp_runtime_events_session_created",
    } <= index_names(MCPRuntimeEvent)
    assert {
        "ix_mcp_tool_invocations_retention",
        "ix_mcp_tool_invocations_workspace_user_started",
        "ix_mcp_tool_invocations_workspace_agent_started",
    } <= index_names(MCPToolInvocation)
    assert {
        "ix_mcp_runtime_sessions_status_expires_at",
        "ix_mcp_runtime_sessions_installation_config_fingerprint",
        "uq_mcp_runtime_sessions_one_active_per_installation",
    } <= index_names(MCPRuntimeSession)


def test_gateway_search_models_declare_database_indexes() -> None:
    assert "ix_mcp_server_installations_enabled_page" in index_names(MCPServerInstallation)
    assert {
        "ix_mcp_server_tool_schemas_search_vector",
        "ix_mcp_server_tool_schemas_active_page",
    } <= index_names(MCPServerToolSchema)


def test_domain_enums_remain_wire_compatible_strings() -> None:
    assert AgentScope.WORKSPACE == "workspace"
    assert MembershipRole.OWNER == "owner"
    assert MCPOperationJobStatus.SUCCEEDED == "succeeded"
