"""add workspace conversations

Revision ID: 202607050001
Revises: 202607040001
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607050001"
down_revision: str | None = "202607040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_conversations",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_conversations_agent_id"),
        "workspace_conversations",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_conversations_created_by_id"),
        "workspace_conversations",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_conversations_is_active"),
        "workspace_conversations",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_conversations_organization_id"),
        "workspace_conversations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_conversations_workspace_id"),
        "workspace_conversations",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
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
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_conversation_messages_conversation_sequence",
        ),
    )
    op.create_index(
        op.f("ix_conversation_messages_conversation_id"),
        "conversation_messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_conversation_messages_conversation_id"),
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index(
        op.f("ix_workspace_conversations_workspace_id"),
        table_name="workspace_conversations",
    )
    op.drop_index(
        op.f("ix_workspace_conversations_organization_id"),
        table_name="workspace_conversations",
    )
    op.drop_index(
        op.f("ix_workspace_conversations_is_active"),
        table_name="workspace_conversations",
    )
    op.drop_index(
        op.f("ix_workspace_conversations_created_by_id"),
        table_name="workspace_conversations",
    )
    op.drop_index(
        op.f("ix_workspace_conversations_agent_id"),
        table_name="workspace_conversations",
    )
    op.drop_table("workspace_conversations")
