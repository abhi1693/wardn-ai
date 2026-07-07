import uuid

from sqlalchemy import Integer, String, UniqueConstraint
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
