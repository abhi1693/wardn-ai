import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_agents_org_name",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="organization", nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class AgentMCPServerAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_mcp_server_assignments"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "installation_id",
            name="uq_agent_mcp_server_assignments_agent_installation",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class AgentMCPToolAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_mcp_tool_assignments"
    __table_args__ = (
        CheckConstraint(
            "(wildcard = true and tool_schema_id is null) "
            "or (wildcard = false and tool_schema_id is not null)",
            name="ck_agent_mcp_tool_assignments_wildcard_shape",
        ),
        UniqueConstraint(
            "server_assignment_id",
            "tool_schema_id",
            name="uq_agent_mcp_tool_assignments_server_tool_schema",
        ),
        Index(
            "uq_agent_mcp_tool_assignments_server_wildcard",
            "server_assignment_id",
            unique=True,
            postgresql_where=text("wildcard is true"),
        ),
    )

    server_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_mcp_server_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_schema_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_tool_schemas.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    wildcard: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
