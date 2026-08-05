"""Improve MCP server catalog search ranking.

Revision ID: 202608050006
Revises: 202608050005
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608050006"
down_revision: str | None = "202608050005"
branch_labels: str | None = None
depends_on: str | None = None

SEARCH_VECTOR_EXPRESSION = """
setweight(to_tsvector('simple'::regconfig, coalesce(name, '')), 'A') ||
setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') ||
setweight(to_tsvector('english'::regconfig, coalesce(description, '')), 'B') ||
setweight(
    to_tsvector(
        'english'::regconfig,
        left(coalesce(server_json #>> '{documentation}', ''), 32768)
    ),
    'C'
)
"""

LEGACY_SEARCH_VECTOR_EXPRESSION = (
    "to_tsvector('simple'::regconfig, "
    "coalesce(name, '') || ' ' || coalesce(title, '') || ' ' || "
    "coalesce(description, ''))"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.drop_index(
        "ix_mcp_server_versions_search_vector",
        table_name="mcp_server_versions",
    )
    op.drop_column("mcp_server_versions", "search_vector")
    op.add_column(
        "mcp_server_versions",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mcp_server_versions_search_vector",
        "mcp_server_versions",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX ix_mcp_server_versions_search_name_trgm "
        "ON mcp_server_versions USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_mcp_server_versions_search_title_trgm "
        "ON mcp_server_versions USING gin (lower(title) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_server_versions_search_title_trgm",
        table_name="mcp_server_versions",
    )
    op.drop_index(
        "ix_mcp_server_versions_search_name_trgm",
        table_name="mcp_server_versions",
    )
    op.drop_index(
        "ix_mcp_server_versions_search_vector",
        table_name="mcp_server_versions",
    )
    op.drop_column("mcp_server_versions", "search_vector")
    op.add_column(
        "mcp_server_versions",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(LEGACY_SEARCH_VECTOR_EXPRESSION, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mcp_server_versions_search_vector",
        "mcp_server_versions",
        ["search_vector"],
        postgresql_using="gin",
    )
