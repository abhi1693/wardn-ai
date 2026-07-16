"""Name organization slug uniqueness and constrain catalog source URLs."""

from alembic import op

revision: str = "202607160003"
down_revision: str | None = "202607160002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organizations "
        "RENAME CONSTRAINT organizations_slug_key TO uq_organizations_slug"
    )
    op.create_unique_constraint(
        "uq_mcp_catalog_sources_org_base_url",
        "mcp_catalog_sources",
        ["organization_id", "base_url"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_mcp_catalog_sources_org_base_url",
        "mcp_catalog_sources",
        type_="unique",
    )
    op.execute(
        "ALTER TABLE organizations "
        "RENAME CONSTRAINT uq_organizations_slug TO organizations_slug_key"
    )
