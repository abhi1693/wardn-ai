"""cache mcp tool schemas

Revision ID: 202606210007
Revises: 202606210006
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210007"
down_revision: str | None = "202606210006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_server_tool_schemas",
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("server_version", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_name",
            "server_version",
            "tool_name",
            name="uq_mcp_server_tool_schemas_server_version_tool",
        ),
    )
    op.create_index(
        op.f("ix_mcp_server_tool_schemas_server_name"),
        "mcp_server_tool_schemas",
        ["server_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_tool_schemas_server_version"),
        "mcp_server_tool_schemas",
        ["server_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_tool_schemas_tool_name"),
        "mcp_server_tool_schemas",
        ["tool_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_tool_schemas_is_active"),
        "mcp_server_tool_schemas",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_server_tool_schemas_is_active"),
        table_name="mcp_server_tool_schemas",
    )
    op.drop_index(
        op.f("ix_mcp_server_tool_schemas_tool_name"),
        table_name="mcp_server_tool_schemas",
    )
    op.drop_index(
        op.f("ix_mcp_server_tool_schemas_server_version"),
        table_name="mcp_server_tool_schemas",
    )
    op.drop_index(
        op.f("ix_mcp_server_tool_schemas_server_name"),
        table_name="mcp_server_tool_schemas",
    )
    op.drop_table("mcp_server_tool_schemas")
