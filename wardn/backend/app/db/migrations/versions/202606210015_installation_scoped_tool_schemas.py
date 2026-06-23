"""scope mcp tool schemas to installations

Revision ID: 202606210015
Revises: 202606210014
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210015"
down_revision: str | None = "202606210014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_tool_schemas",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mcp_server_tool_schemas",
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_mcp_server_tool_schemas_workspace_id"),
        "mcp_server_tool_schemas",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_tool_schemas_installation_id"),
        "mcp_server_tool_schemas",
        ["installation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_mcp_server_tool_schemas_workspace_id_workspaces",
        "mcp_server_tool_schemas",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_mcp_server_tool_schemas_installation_id_installations",
        "mcp_server_tool_schemas",
        "mcp_server_installations",
        ["installation_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        sa.text(
            """
            update mcp_server_tool_schemas tools
            set
                installation_id = matched.installation_id,
                workspace_id = matched.workspace_id
            from (
                select
                    (array_agg(installs.id))[1] as installation_id,
                    (array_agg(installs.workspace_id))[1] as workspace_id,
                    tools.id as tool_schema_id
                from mcp_server_tool_schemas tools
                join mcp_server_installations installs
                  on installs.server_name = tools.server_name
                 and installs.installed_version = tools.server_version
                group by tools.id
                having count(installs.id) = 1
            ) matched
            where tools.id = matched.tool_schema_id
            """
        )
    )

    op.drop_constraint(
        "uq_mcp_server_tool_schemas_server_version_tool",
        "mcp_server_tool_schemas",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_mcp_server_tool_schemas_installation_tool",
        "mcp_server_tool_schemas",
        ["installation_id", "tool_name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_mcp_server_tool_schemas_installation_tool",
        "mcp_server_tool_schemas",
        type_="unique",
    )
    op.execute(
        sa.text(
            """
            delete from mcp_server_tool_schemas tools
            using (
                select
                    id,
                    row_number() over (
                        partition by server_name, server_version, tool_name
                        order by created_at, id
                    ) as row_number
                from mcp_server_tool_schemas
            ) ranked
            where tools.id = ranked.id
              and ranked.row_number > 1
            """
        )
    )
    op.create_unique_constraint(
        "uq_mcp_server_tool_schemas_server_version_tool",
        "mcp_server_tool_schemas",
        ["server_name", "server_version", "tool_name"],
    )
    op.drop_constraint(
        "fk_mcp_server_tool_schemas_installation_id_installations",
        "mcp_server_tool_schemas",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_mcp_server_tool_schemas_workspace_id_workspaces",
        "mcp_server_tool_schemas",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_mcp_server_tool_schemas_installation_id"),
        table_name="mcp_server_tool_schemas",
    )
    op.drop_index(
        op.f("ix_mcp_server_tool_schemas_workspace_id"),
        table_name="mcp_server_tool_schemas",
    )
    op.drop_column("mcp_server_tool_schemas", "installation_id")
    op.drop_column("mcp_server_tool_schemas", "workspace_id")
