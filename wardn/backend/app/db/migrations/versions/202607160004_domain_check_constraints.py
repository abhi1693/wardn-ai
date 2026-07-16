"""Constrain domain values and scoped foreign-key invariants.

Revision ID: 202607160004
Revises: 202607160003
Create Date: 2026-07-16 00:04:00.000000
"""

from alembic import op

revision: str = "202607160004"
down_revision: str | None = "202607160003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_organizations_status",
        "organizations",
        "status IN ('active', 'suspended', 'archived')",
    )
    op.create_check_constraint(
        "ck_organization_memberships_role",
        "organization_memberships",
        "role IN ('owner', 'admin', 'member')",
    )
    op.create_check_constraint(
        "ck_workspaces_status",
        "workspaces",
        "status IN ('active', 'archived')",
    )
    op.create_check_constraint(
        "ck_workspace_memberships_role",
        "workspace_memberships",
        "role IN ('owner', 'admin', 'member')",
    )
    op.create_check_constraint(
        "ck_agents_scope",
        "agents",
        "scope IN ('organization', 'workspace')",
    )
    op.create_check_constraint(
        "ck_agents_scope_workspace",
        "agents",
        "(scope = 'organization' AND workspace_id IS NULL) OR "
        "(scope = 'workspace' AND workspace_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_conversation_messages_role",
        "conversation_messages",
        "role IN ('system', 'user', 'assistant')",
    )
    op.create_check_constraint(
        "ck_llm_provider_credentials_visibility",
        "llm_provider_credentials",
        "visibility IN ('organization', 'workspace', 'user')",
    )
    op.create_check_constraint(
        "ck_llm_provider_credentials_visibility_scope",
        "llm_provider_credentials",
        "(visibility = 'organization' AND workspace_id IS NULL AND user_id IS NULL) OR "
        "(visibility = 'workspace' AND workspace_id IS NOT NULL AND user_id IS NULL) OR "
        "(visibility = 'user' AND workspace_id IS NULL AND user_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_llm_provider_credentials_auth_method",
        "llm_provider_credentials",
        "auth_method IN ('api_key', 'oauth')",
    )
    op.create_check_constraint(
        "ck_llm_provider_credentials_auth_material",
        "llm_provider_credentials",
        "(auth_method = 'api_key' AND api_key_secret_handle_id IS NOT NULL) OR "
        "(auth_method = 'oauth' AND oauth_provider = 'chatgpt' "
        "AND oauth_access_token_secret_handle_id IS NOT NULL "
        "AND oauth_refresh_token_secret_handle_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_mcp_server_versions_status",
        "mcp_server_versions",
        "status IN ('active', 'deprecated', 'deleted')",
    )
    op.create_check_constraint(
        "ck_mcp_catalog_sources_provider",
        "mcp_catalog_sources",
        "provider IN ('wardn_hub', 'official', 'pulsemcp', 'custom')",
    )
    op.create_check_constraint(
        "ck_mcp_catalog_sources_sync_mode",
        "mcp_catalog_sources",
        "sync_mode IN ('latest_only', 'all_versions')",
    )
    op.create_check_constraint(
        "ck_mcp_server_installations_status",
        "mcp_server_installations",
        "status IN ('enabled', 'disabled')",
    )
    op.create_check_constraint(
        "ck_mcp_operation_jobs_status",
        "mcp_operation_jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_mcp_operation_jobs_cleanup_status",
        "mcp_operation_jobs",
        "cleanup_status IN ('not_required', 'pending', 'running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "ck_mcp_operation_jobs_progress",
        "mcp_operation_jobs",
        "progress_current >= 0 AND progress_total >= 1 AND progress_current <= progress_total",
    )
    op.create_check_constraint(
        "ck_mcp_operation_jobs_attempts",
        "mcp_operation_jobs",
        "attempt_count >= 0 AND max_attempts >= 1 "
        "AND cleanup_attempt_count >= 0 AND cleanup_max_attempts >= 1",
    )


def downgrade() -> None:
    for table_name, constraint_name in (
        ("mcp_operation_jobs", "ck_mcp_operation_jobs_attempts"),
        ("mcp_operation_jobs", "ck_mcp_operation_jobs_progress"),
        ("mcp_operation_jobs", "ck_mcp_operation_jobs_cleanup_status"),
        ("mcp_operation_jobs", "ck_mcp_operation_jobs_status"),
        ("mcp_server_installations", "ck_mcp_server_installations_status"),
        ("mcp_catalog_sources", "ck_mcp_catalog_sources_sync_mode"),
        ("mcp_catalog_sources", "ck_mcp_catalog_sources_provider"),
        ("mcp_server_versions", "ck_mcp_server_versions_status"),
        ("llm_provider_credentials", "ck_llm_provider_credentials_auth_material"),
        ("llm_provider_credentials", "ck_llm_provider_credentials_auth_method"),
        ("llm_provider_credentials", "ck_llm_provider_credentials_visibility_scope"),
        ("llm_provider_credentials", "ck_llm_provider_credentials_visibility"),
        ("conversation_messages", "ck_conversation_messages_role"),
        ("agents", "ck_agents_scope_workspace"),
        ("agents", "ck_agents_scope"),
        ("workspace_memberships", "ck_workspace_memberships_role"),
        ("workspaces", "ck_workspaces_status"),
        ("organization_memberships", "ck_organization_memberships_role"),
        ("organizations", "ck_organizations_status"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="check")
