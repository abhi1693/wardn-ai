"""add workspace chat provider connections

Revision ID: 202608020002
Revises: 202608020001
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608020002"
down_revision: str | None = "202608020001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_provider_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('telegram', 'whatsapp_local')",
            name="ck_chat_provider_connections_provider",
        ),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_chat_provider_connections_name"),
        sa.CheckConstraint(
            "btrim(external_id) <> ''",
            name="ck_chat_provider_connections_external_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_provider_connections_created_by_id",
        "chat_provider_connections",
        ["created_by_id"],
    )
    op.create_index(
        "ix_chat_provider_connections_is_active",
        "chat_provider_connections",
        ["is_active"],
    )
    op.create_index(
        "ix_chat_provider_connections_organization_id",
        "chat_provider_connections",
        ["organization_id"],
    )
    op.create_index(
        "ix_chat_provider_connections_provider",
        "chat_provider_connections",
        ["provider"],
    )
    op.create_index(
        "ix_chat_provider_connections_workspace_id",
        "chat_provider_connections",
        ["workspace_id"],
    )
    op.create_index(
        "uq_chat_provider_connections_workspace_name",
        "chat_provider_connections",
        ["workspace_id", "name"],
        unique=True,
    )
    op.create_index(
        "uq_chat_provider_connections_workspace_provider_external",
        "chat_provider_connections",
        ["workspace_id", "provider", "external_id"],
        unique=True,
    )

    op.create_table(
        "chat_provider_connection_secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("secret_handle_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(purpose) <> ''",
            name="ck_chat_provider_connection_secrets_purpose",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["chat_provider_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["secret_handle_id"],
            ["secret_handles.id"],
            name="fk_chat_provider_connection_secrets_secret_handle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_provider_connection_secrets_connection_id",
        "chat_provider_connection_secrets",
        ["connection_id"],
    )
    op.create_index(
        "ix_chat_provider_connection_secrets_organization_id",
        "chat_provider_connection_secrets",
        ["organization_id"],
    )
    op.create_index(
        "ix_chat_provider_connection_secrets_purpose",
        "chat_provider_connection_secrets",
        ["purpose"],
    )
    op.create_index(
        "ix_chat_provider_connection_secrets_secret_handle_id",
        "chat_provider_connection_secrets",
        ["secret_handle_id"],
    )
    op.create_index(
        "ix_chat_provider_connection_secrets_workspace_id",
        "chat_provider_connection_secrets",
        ["workspace_id"],
    )
    op.create_index(
        "uq_chat_provider_connection_secrets_connection_purpose",
        "chat_provider_connection_secrets",
        ["connection_id", "purpose"],
        unique=True,
    )

    op.create_table(
        "chat_provider_threads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("external_thread_id", sa.String(length=255), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column(
            "external_user_display_name",
            sa.String(length=255),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "last_external_message_id",
            sa.String(length=255),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "provider_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(external_thread_id) <> ''",
            name="ck_chat_provider_threads_external_thread_id",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["chat_provider_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_provider_threads_connection_id",
        "chat_provider_threads",
        ["connection_id"],
    )
    op.create_index(
        "ix_chat_provider_threads_conversation_id",
        "chat_provider_threads",
        ["conversation_id"],
    )
    op.create_index(
        "ix_chat_provider_threads_organization_id",
        "chat_provider_threads",
        ["organization_id"],
    )
    op.create_index(
        "ix_chat_provider_threads_workspace_id",
        "chat_provider_threads",
        ["workspace_id"],
    )
    op.create_index(
        "uq_chat_provider_threads_connection_external",
        "chat_provider_threads",
        ["connection_id", "external_thread_id"],
        unique=True,
    )

    op.create_table(
        "chat_provider_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="received", nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'status')",
            name="ck_chat_provider_events_direction",
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processing', 'processed', 'ignored', 'failed', 'sent')",
            name="ck_chat_provider_events_status",
        ),
        sa.CheckConstraint(
            "btrim(external_event_id) <> ''",
            name="ck_chat_provider_events_external_event_id",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["chat_provider_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["workspace_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["chat_provider_threads.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_provider_events_connection_id",
        "chat_provider_events",
        ["connection_id"],
    )
    op.create_index(
        "ix_chat_provider_events_conversation_id",
        "chat_provider_events",
        ["conversation_id"],
    )
    op.create_index(
        "ix_chat_provider_events_direction",
        "chat_provider_events",
        ["direction"],
    )
    op.create_index(
        "ix_chat_provider_events_organization_id",
        "chat_provider_events",
        ["organization_id"],
    )
    op.create_index("ix_chat_provider_events_provider", "chat_provider_events", ["provider"])
    op.create_index("ix_chat_provider_events_status", "chat_provider_events", ["status"])
    op.create_index("ix_chat_provider_events_thread_id", "chat_provider_events", ["thread_id"])
    op.create_index(
        "ix_chat_provider_events_workspace_created",
        "chat_provider_events",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_chat_provider_events_workspace_id",
        "chat_provider_events",
        ["workspace_id"],
    )
    op.create_index(
        "uq_chat_provider_events_connection_external",
        "chat_provider_events",
        ["connection_id", "external_event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_chat_provider_events_connection_external",
        table_name="chat_provider_events",
    )
    op.drop_index("ix_chat_provider_events_workspace_id", table_name="chat_provider_events")
    op.drop_index(
        "ix_chat_provider_events_workspace_created",
        table_name="chat_provider_events",
    )
    op.drop_index("ix_chat_provider_events_thread_id", table_name="chat_provider_events")
    op.drop_index("ix_chat_provider_events_status", table_name="chat_provider_events")
    op.drop_index("ix_chat_provider_events_provider", table_name="chat_provider_events")
    op.drop_index("ix_chat_provider_events_organization_id", table_name="chat_provider_events")
    op.drop_index("ix_chat_provider_events_direction", table_name="chat_provider_events")
    op.drop_index("ix_chat_provider_events_conversation_id", table_name="chat_provider_events")
    op.drop_index("ix_chat_provider_events_connection_id", table_name="chat_provider_events")
    op.drop_table("chat_provider_events")

    op.drop_index(
        "uq_chat_provider_threads_connection_external",
        table_name="chat_provider_threads",
    )
    op.drop_index("ix_chat_provider_threads_workspace_id", table_name="chat_provider_threads")
    op.drop_index("ix_chat_provider_threads_organization_id", table_name="chat_provider_threads")
    op.drop_index("ix_chat_provider_threads_conversation_id", table_name="chat_provider_threads")
    op.drop_index("ix_chat_provider_threads_connection_id", table_name="chat_provider_threads")
    op.drop_table("chat_provider_threads")

    op.drop_index(
        "uq_chat_provider_connection_secrets_connection_purpose",
        table_name="chat_provider_connection_secrets",
    )
    op.drop_index(
        "ix_chat_provider_connection_secrets_workspace_id",
        table_name="chat_provider_connection_secrets",
    )
    op.drop_index(
        "ix_chat_provider_connection_secrets_secret_handle_id",
        table_name="chat_provider_connection_secrets",
    )
    op.drop_index(
        "ix_chat_provider_connection_secrets_purpose",
        table_name="chat_provider_connection_secrets",
    )
    op.drop_index(
        "ix_chat_provider_connection_secrets_organization_id",
        table_name="chat_provider_connection_secrets",
    )
    op.drop_index(
        "ix_chat_provider_connection_secrets_connection_id",
        table_name="chat_provider_connection_secrets",
    )
    op.drop_table("chat_provider_connection_secrets")

    op.drop_index(
        "uq_chat_provider_connections_workspace_provider_external",
        table_name="chat_provider_connections",
    )
    op.drop_index(
        "uq_chat_provider_connections_workspace_name",
        table_name="chat_provider_connections",
    )
    op.drop_index(
        "ix_chat_provider_connections_workspace_id",
        table_name="chat_provider_connections",
    )
    op.drop_index(
        "ix_chat_provider_connections_provider",
        table_name="chat_provider_connections",
    )
    op.drop_index(
        "ix_chat_provider_connections_organization_id",
        table_name="chat_provider_connections",
    )
    op.drop_index(
        "ix_chat_provider_connections_is_active",
        table_name="chat_provider_connections",
    )
    op.drop_index(
        "ix_chat_provider_connections_created_by_id",
        table_name="chat_provider_connections",
    )
    op.drop_table("chat_provider_connections")
