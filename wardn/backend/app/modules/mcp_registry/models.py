from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MCPServerVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_versions"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    status_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    repository: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    packages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    remotes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    icons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    server_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class MCPServerInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_installations"

    server_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    installed_version: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="enabled", nullable=False, index=True)
    install_type: Mapped[str] = mapped_column(String(32), default="metadata", nullable=False)
    install_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    runtime_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    secret_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    install_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
