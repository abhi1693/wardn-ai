from app.db.domain_types import AgentScope, MCPOperationJobStatus, MembershipRole
from app.modules.agents.models import Agent, ConversationMessage
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPOperationJob,
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)


def constraint_names(model: type) -> set[str]:
    return {constraint.name for constraint in model.__table__.constraints if constraint.name}


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


def test_domain_enums_remain_wire_compatible_strings() -> None:
    assert AgentScope.WORKSPACE == "workspace"
    assert MembershipRole.OWNER == "owner"
    assert MCPOperationJobStatus.SUCCEEDED == "succeeded"
