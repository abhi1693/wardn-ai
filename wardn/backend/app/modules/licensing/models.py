import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class LicenseInstallation(TimestampMixin, Base):
    """Local identity and the last license-server-signed entitlement lease."""

    __tablename__ = "license_installations"

    singleton_key: Mapped[str] = mapped_column(String(16), primary_key=True, default="wardn")
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    signed_lease: Mapped[str] = mapped_column(Text, default="", nullable=False)
    renewal_token: Mapped[str] = mapped_column(Text, default="", nullable=False)
    lease_imported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
