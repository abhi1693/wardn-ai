import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.domain_types import (
    ChatProviderEventDirection,
    ChatProviderEventStatus,
    ChatProviderType,
)
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ChatProviderConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_provider_connections"
    __table_args__ = (
        Index(
            "uq_chat_provider_connections_workspace_name",
            "workspace_id",
            "name",
            unique=True,
        ),
        Index(
            "uq_chat_provider_connections_workspace_provider_external",
            "workspace_id",
            "provider",
            "external_id",
            unique=True,
        ),
        CheckConstraint(
            "provider IN ('telegram', 'whatsapp_local', 'slack')",
            name="ck_chat_provider_connections_provider",
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_chat_provider_connections_name"),
        CheckConstraint(
            "btrim(external_id) <> ''",
            name="ck_chat_provider_connections_external_id",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[ChatProviderType] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class ChatProviderConnectionSecret(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_provider_connection_secrets"
    __table_args__ = (
        Index(
            "uq_chat_provider_connection_secrets_connection_purpose",
            "connection_id",
            "purpose",
            unique=True,
        ),
        CheckConstraint(
            "btrim(purpose) <> ''",
            name="ck_chat_provider_connection_secrets_purpose",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_provider_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    secret_handle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "secret_handles.id",
            name="fk_chat_provider_connection_secrets_secret_handle",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )


class ChatProviderThread(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_provider_threads"
    __table_args__ = (
        Index(
            "uq_chat_provider_threads_connection_external",
            "connection_id",
            "external_thread_id",
            unique=True,
        ),
        CheckConstraint(
            "btrim(external_thread_id) <> ''",
            name="ck_chat_provider_threads_external_thread_id",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_provider_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    external_user_display_name: Mapped[str] = mapped_column(
        String(255),
        default="",
        nullable=False,
    )
    last_external_message_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ChatProviderEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_provider_events"
    __table_args__ = (
        Index(
            "uq_chat_provider_events_connection_external",
            "connection_id",
            "external_event_id",
            unique=True,
        ),
        Index(
            "ix_chat_provider_events_workspace_created",
            "workspace_id",
            "created_at",
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound', 'status')",
            name="ck_chat_provider_events_direction",
        ),
        CheckConstraint(
            "status IN ('received', 'processing', 'processed', 'ignored', 'failed', 'sent')",
            name="ck_chat_provider_events_status",
        ),
        CheckConstraint(
            "btrim(external_event_id) <> ''",
            name="ck_chat_provider_events_external_event_id",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_provider_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_provider_threads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[ChatProviderType] = mapped_column(String(32), nullable=False, index=True)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[ChatProviderEventDirection] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ChatProviderEventStatus] = mapped_column(
        String(32),
        default=ChatProviderEventStatus.RECEIVED,
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
