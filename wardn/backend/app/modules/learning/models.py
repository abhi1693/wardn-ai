import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class LearningEventStream(Base):
    """Transactional allocator; unlike BIGSERIAL this cannot expose commit-order holes."""

    __tablename__ = "learning_event_streams"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class LearningEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_learning_execution_sequence"),
        UniqueConstraint(
            "workspace_id", "workspace_sequence", name="uq_learning_workspace_sequence"
        ),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_learning_event_idempotency"),
        CheckConstraint(
            "sequence_number > 0 AND workspace_sequence > 0", name="ck_learning_sequence"
        ),
        CheckConstraint(
            "execution_kind IN ('agent_run', 'scheduled_run', 'tool_invocation')",
            name="ck_learning_execution_kind",
        ),
        Index("ix_learning_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_learning_conversation_occurred", "conversation_id", "occurred_at"),
        Index("ix_learning_type_occurred", "event_type", "occurred_at"),
        Index("ix_learning_objective", "objective_id"),
        Index("ix_learning_tool_call", "tool_call_id"),
        Index("ix_learning_scheduled_run", "scheduled_run_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Immutable provenance IDs deliberately survive deletion/retention of source rows.
    # The emitter validates their tenant and relationships before insertion.
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    objective_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scheduled_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scheduled_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    span_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class LearningWorkerCursor(TimestampMixin, Base):
    __tablename__ = "learning_worker_cursors"
    __table_args__ = (CheckConstraint("last_sequence >= 0", name="ck_learning_cursor_sequence"),)

    worker_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
