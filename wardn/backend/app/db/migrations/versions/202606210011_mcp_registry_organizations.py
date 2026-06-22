"""Scope MCP registry servers to organizations.

Revision ID: 202606210011
Revises: 202606210010
Create Date: 2026-06-21 00:11:00.000000
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210011"
down_revision: str | None = "202606210010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def unique_constraint_names(table_name: str) -> set[str]:
    return {
        constraint.get("name") or ""
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    }


def index_names(table_name: str) -> set[str]:
    return {index.get("name") or "" for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def default_organization_id() -> object:
    bind = op.get_bind()
    organization_id = bind.execute(
        sa.text("select id from organizations where slug = 'default'")
    ).scalar()
    if organization_id:
        return organization_id

    organization_id = uuid4()
    bind.execute(
        sa.text(
            """
            insert into organizations (id, name, slug, status, created_at, updated_at)
            values (:id, 'Default Organization', 'default', 'active', now(), now())
            """
        ),
        {"id": organization_id},
    )
    return organization_id


def upgrade() -> None:
    columns = column_names("mcp_server_versions")
    if "organization_id" not in columns:
        op.add_column(
            "mcp_server_versions",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    organization_id = default_organization_id()
    op.get_bind().execute(
        sa.text(
            """
            update mcp_server_versions
            set organization_id = :organization_id
            where organization_id is null
            """
        ),
        {"organization_id": organization_id},
    )

    indexes = index_names("mcp_server_versions")
    if "ix_mcp_server_versions_organization_id" not in indexes:
        op.create_index(
            "ix_mcp_server_versions_organization_id",
            "mcp_server_versions",
            ["organization_id"],
        )

    op.create_foreign_key(
        "fk_mcp_server_versions_organization_id_organizations",
        "mcp_server_versions",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )

    constraints = unique_constraint_names("mcp_server_versions")
    if "uq_mcp_server_versions_name_version" in constraints:
        op.drop_constraint(
            "uq_mcp_server_versions_name_version",
            "mcp_server_versions",
            type_="unique",
        )
    if "uq_mcp_server_versions_org_name_version" not in constraints:
        op.create_unique_constraint(
            "uq_mcp_server_versions_org_name_version",
            "mcp_server_versions",
            ["organization_id", "name", "version"],
        )

    op.alter_column("mcp_server_versions", "organization_id", nullable=False)


def downgrade() -> None:
    constraints = unique_constraint_names("mcp_server_versions")
    if "uq_mcp_server_versions_org_name_version" in constraints:
        op.drop_constraint(
            "uq_mcp_server_versions_org_name_version",
            "mcp_server_versions",
            type_="unique",
        )
    if "uq_mcp_server_versions_name_version" not in constraints:
        op.create_unique_constraint(
            "uq_mcp_server_versions_name_version",
            "mcp_server_versions",
            ["name", "version"],
        )

    op.drop_constraint(
        "fk_mcp_server_versions_organization_id_organizations",
        "mcp_server_versions",
        type_="foreignkey",
    )
    indexes = index_names("mcp_server_versions")
    if "ix_mcp_server_versions_organization_id" in indexes:
        op.drop_index("ix_mcp_server_versions_organization_id", table_name="mcp_server_versions")
    if "organization_id" in column_names("mcp_server_versions"):
        op.drop_column("mcp_server_versions", "organization_id")
