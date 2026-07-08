"""Add named MCP server installation configs.

Revision ID: 202606210009
Revises: 202606210008
Create Date: 2026-06-21 00:09:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606210009"
down_revision: str | None = "202606210008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("mcp_server_installations")}
    if "config_name" not in columns:
        op.add_column(
            "mcp_server_installations",
            sa.Column(
                "config_name",
                sa.String(length=100),
                nullable=False,
                server_default="default",
            ),
        )

    unique_constraints = inspector.get_unique_constraints("mcp_server_installations")
    for constraint in unique_constraints:
        if constraint.get("column_names") == ["server_name"] and constraint.get("name"):
            op.drop_constraint(
                constraint["name"],
                "mcp_server_installations",
                type_="unique",
            )

    existing_constraints = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("mcp_server_installations")
    }
    if "uq_mcp_server_installations_server_config" not in existing_constraints:
        op.create_unique_constraint(
            "uq_mcp_server_installations_server_config",
            "mcp_server_installations",
            ["server_name", "config_name"],
        )
    op.alter_column("mcp_server_installations", "config_name", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("mcp_server_installations")
    if any(
        constraint.get("name") == "uq_mcp_server_installations_server_config"
        for constraint in unique_constraints
    ):
        op.drop_constraint(
            "uq_mcp_server_installations_server_config",
            "mcp_server_installations",
            type_="unique",
        )
    if not any(
        constraint.get("column_names") == ["server_name"]
        for constraint in unique_constraints
    ):
        op.create_unique_constraint(
            "mcp_server_installations_server_name_key",
            "mcp_server_installations",
            ["server_name"],
        )
    columns = {column["name"] for column in inspector.get_columns("mcp_server_installations")}
    if "config_name" in columns:
        op.drop_column("mcp_server_installations", "config_name")
