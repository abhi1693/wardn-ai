"""Add indexed MCP gateway search and keyset pagination support.

Revision ID: 202607170002
Revises: 202607170001
Create Date: 2026-07-17 00:02:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607170002"
down_revision: str | None = "202607170001"
branch_labels: str | None = None
depends_on: str | None = None

TOOL_SEARCH_VECTOR_SQL = (
    "to_tsvector('simple'::regconfig, "
    "coalesce(server_name, '') || ' ' || coalesce(tool_name, '') || ' ' || "
    "coalesce(title, '') || ' ' || coalesce(description, ''))"
)


def upgrade() -> None:
    op.add_column(
        "mcp_server_tool_schemas",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(TOOL_SEARCH_VECTOR_SQL, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mcp_server_tool_schemas_search_vector",
        "mcp_server_tool_schemas",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_mcp_server_tool_schemas_active_page",
        "mcp_server_tool_schemas",
        ["server_name", "tool_name", "id"],
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_mcp_server_installations_enabled_page",
        "mcp_server_installations",
        ["server_name", "id"],
        postgresql_where=sa.text("status = 'enabled'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_server_installations_enabled_page",
        table_name="mcp_server_installations",
    )
    op.drop_index(
        "ix_mcp_server_tool_schemas_active_page",
        table_name="mcp_server_tool_schemas",
    )
    op.drop_index(
        "ix_mcp_server_tool_schemas_search_vector",
        table_name="mcp_server_tool_schemas",
    )
    op.drop_column("mcp_server_tool_schemas", "search_vector")
