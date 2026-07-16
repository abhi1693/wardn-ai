import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.mcp_runtime.models import MCPToolInvocation as MCPToolUsageRecord

__all__ = ["LLMModelPrice", "LLMTrace", "LLMUsageRecord", "MCPToolUsageRecord"]


class LLMModelPrice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_model_prices"
    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_llm_model_prices_provider_model"),
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    input_usd_per_1m_tokens: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    output_usd_per_1m_tokens: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    cache_read_usd_per_1m_tokens: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10),
        nullable=True,
    )
    cache_write_usd_per_1m_tokens: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10),
        nullable=True,
    )


class LLMTrace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_traces"
    __table_args__ = (
        Index("ix_llm_traces_trace_span", "trace_id", "span_id"),
    )

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        default=Decimal("0"),
        nullable=False,
    )


class LLMUsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_usage_records"
    __table_args__ = (
        Index(
            "ix_llm_usage_records_org_user_started",
            "organization_id",
            "user_id",
            "started_at",
        ),
        Index(
            "ix_llm_usage_records_org_agent_started",
            "organization_id",
            "agent_id",
            "started_at",
        ),
        Index(
            "ix_llm_usage_records_org_model_started",
            "organization_id",
            "provider",
            "model",
            "started_at",
        ),
        Index(
            "ix_llm_usage_records_org_started",
            "organization_id",
            "started_at",
        ),
        Index(
            "ix_llm_usage_records_workspace_started",
            "workspace_id",
            "started_at",
        ),
        Index(
            "ix_llm_usage_records_user_started",
            "user_id",
            "started_at",
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        default=Decimal("0"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    span_id: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
