"""Add runtime events.

Revision ID: 202606210014
Revises: 202606210013
Create Date: 2026-06-21 00:14:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210014"
down_revision: str | None = "202606210013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_runtime_events",
        sa.Column("runtime_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.ForeignKeyConstraint(
            ["runtime_session_id"],
            ["mcp_runtime_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_runtime_events_runtime_session_id",
        "mcp_runtime_events",
        ["runtime_session_id"],
    )
    op.create_index(
        "ix_mcp_runtime_events_event_type",
        "mcp_runtime_events",
        ["event_type"],
    )
    op.create_index(
        "ix_mcp_runtime_events_session_created",
        "mcp_runtime_events",
        ["runtime_session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_runtime_events_session_created", table_name="mcp_runtime_events")
    op.drop_index("ix_mcp_runtime_events_event_type", table_name="mcp_runtime_events")
    op.drop_index("ix_mcp_runtime_events_runtime_session_id", table_name="mcp_runtime_events")
    op.drop_table("mcp_runtime_events")
