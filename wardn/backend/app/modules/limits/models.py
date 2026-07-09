import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ResourceLimit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_limits"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "limit_key",
            name="uq_resource_limits_scope_key",
        ),
    )

    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    limit_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


class UsageBudget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "usage_budgets"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "budget_key",
            "model_filter",
            name="uq_usage_budgets_scope_key_model",
        ),
        Index("ix_usage_budgets_scope_key", "scope_type", "scope_id", "budget_key"),
    )

    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    budget_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    period_anchor: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    model_filter: Mapped[str] = mapped_column(String(255), default="", nullable=False)
