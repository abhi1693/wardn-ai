"""Scale MCP catalog search, ownership, pagination, and synchronization.

Revision ID: 202607160008
Revises: 202607160007
Create Date: 2026-07-16 00:08:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607160008"
down_revision: str | None = "202607160007"
branch_labels: str | None = None
depends_on: str | None = None

SEARCH_VECTOR_SQL = (
    "to_tsvector('simple'::regconfig, "
    "coalesce(name, '') || ' ' || coalesce(title, '') || ' ' || "
    "coalesce(description, ''))"
)


def upgrade() -> None:
    op.add_column(
        "mcp_server_versions",
        sa.Column(
            "catalog_source_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_mcp_server_versions_catalog_source",
        "mcp_server_versions",
        "mcp_catalog_sources",
        ["catalog_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            """
            UPDATE mcp_server_versions AS version
            SET catalog_source_id = source.id
            FROM mcp_catalog_sources AS source
            WHERE source.organization_id = version.organization_id
              AND source.id::text = (
                  version.server_json #>> '{_meta,wardnCatalogSource,id}'
              )
            """
        )
    )
    op.add_column(
        "mcp_server_versions",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_SQL, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mcp_server_versions_search_vector",
        "mcp_server_versions",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_mcp_server_versions_catalog_source",
        "mcp_server_versions",
        ["organization_id", "catalog_source_id"],
        postgresql_where=sa.text("catalog_source_id IS NOT NULL"),
    )
    op.create_index(
        "ix_mcp_server_versions_org_latest_page",
        "mcp_server_versions",
        ["organization_id", "is_latest", "name", "version", "id"],
        postgresql_where=sa.text("status <> 'deleted'"),
    )
    op.create_index(
        "ix_mcp_server_versions_org_page",
        "mcp_server_versions",
        ["organization_id", "name", "version", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_server_versions_org_page", table_name="mcp_server_versions")
    op.drop_index(
        "ix_mcp_server_versions_org_latest_page",
        table_name="mcp_server_versions",
    )
    op.drop_index(
        "ix_mcp_server_versions_catalog_source",
        table_name="mcp_server_versions",
    )
    op.drop_index(
        "ix_mcp_server_versions_search_vector",
        table_name="mcp_server_versions",
    )
    op.drop_column("mcp_server_versions", "search_vector")
    op.drop_constraint(
        "fk_mcp_server_versions_catalog_source",
        "mcp_server_versions",
        type_="foreignkey",
    )
    op.drop_column("mcp_server_versions", "catalog_source_id")
