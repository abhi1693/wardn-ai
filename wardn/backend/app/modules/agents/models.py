import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.domain_types import AgentScope, ConversationRole
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index(
            "uq_agents_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("workspace_id is null"),
        ),
        CheckConstraint(
            "scope IN ('organization', 'workspace')",
            name="ck_agents_scope",
        ),
        CheckConstraint(
            "(scope = 'organization' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_agents_scope_workspace",
        ),
        Index(
            "uq_agents_workspace_name",
            "organization_id",
            "workspace_id",
            "name",
            unique=True,
            postgresql_where=text("workspace_id is not null"),
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
    scope: Mapped[AgentScope] = mapped_column(
        String(32),
        default=AgentScope.ORGANIZATION,
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class WorkspaceConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_conversations"

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
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), default="New chat", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class ConversationMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_conversation_messages_conversation_sequence",
        ),
        CheckConstraint(
            "role IN ('system', 'user', 'assistant')",
            name="ck_conversation_messages_role",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role: Mapped[ConversationRole] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parts: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

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
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_type: Mapped[str] = mapped_column(String(32), default="chat", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class AgentRunStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_run_steps"
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "sequence",
            name="uq_agent_run_steps_run_sequence",
        ),
    )

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mcp_tool_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_tool_invocations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AgentToolApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_tool_approvals"
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "tool_call_id",
            name="uq_agent_tool_approvals_run_tool_call",
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
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_tool_schemas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


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
