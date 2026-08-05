import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.domain_types import (
    WorkspaceScheduledTaskConversationPolicy,
    WorkspaceScheduledTaskDeliveryStatus,
    WorkspaceScheduledTaskMonitoringStatus,
    WorkspaceScheduledTaskNotificationEvent,
    WorkspaceScheduledTaskNotificationStatus,
    WorkspaceScheduledTaskRunStatus,
    WorkspaceScheduledTaskScheduleType,
)
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceScheduledTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_scheduled_tasks"
    __table_args__ = (
        Index(
            "uq_workspace_scheduled_tasks_workspace_name",
            "workspace_id",
            "name",
            unique=True,
        ),
        Index(
            "ix_workspace_scheduled_tasks_due",
            "is_active",
            "next_run_at",
        ),
        CheckConstraint(
            (
                "schedule_type IN ("
                "'manual', 'interval', 'daily', 'weekly', 'weekdays', 'monthly', "
                "'cron', 'multiple'"
                ")"
            ),
            name="ck_workspace_scheduled_tasks_schedule_type",
        ),
        CheckConstraint(
            "conversation_policy IN ('reuse', 'new_each_run')",
            name="ck_workspace_scheduled_tasks_conversation_policy",
        ),
        CheckConstraint(
            (
                "monitoring_status IN ("
                "'off', 'watching', 'baseline', 'changed', 'unchanged', "
                "'no_output', 'stopped'"
                ")"
            ),
            name="ck_workspace_scheduled_tasks_monitoring_status",
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_workspace_scheduled_tasks_name"),
        CheckConstraint(
            "btrim(instructions) <> ''",
            name="ck_workspace_scheduled_tasks_instructions",
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
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_task_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    last_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_type: Mapped[WorkspaceScheduledTaskScheduleType] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    schedule_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    output_routes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    notification_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    notification_routes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    approval_routes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    monitoring_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    monitoring_status: Mapped[WorkspaceScheduledTaskMonitoringStatus] = mapped_column(
        String(32),
        default=WorkspaceScheduledTaskMonitoringStatus.OFF,
        nullable=False,
        index=True,
    )
    notification_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    conversation_policy: Mapped[WorkspaceScheduledTaskConversationPolicy] = mapped_column(
        String(32),
        default=WorkspaceScheduledTaskConversationPolicy.REUSE,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)


class WorkspaceScheduledTaskSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_scheduled_task_schedules"
    __table_args__ = (
        Index(
            "ix_workspace_scheduled_task_schedules_due",
            "is_active",
            "next_run_at",
        ),
        Index(
            "ix_workspace_scheduled_task_schedules_task_order",
            "task_id",
            "sort_order",
        ),
        CheckConstraint(
            "schedule_type IN ('interval', 'daily', 'weekly', 'weekdays', 'monthly', 'cron')",
            name="ck_workspace_scheduled_task_schedules_schedule_type",
        ),
        CheckConstraint("sort_order >= 0", name="ck_workspace_scheduled_task_schedules_sort_order"),
        CheckConstraint(
            "(starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at)",
            name="ck_workspace_scheduled_task_schedules_window",
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
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    schedule_type: Mapped[WorkspaceScheduledTaskScheduleType] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    schedule_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class WorkspaceScheduledTaskRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_scheduled_task_runs"
    __table_args__ = (
        Index(
            "ix_workspace_scheduled_task_runs_task_scheduled",
            "task_id",
            "scheduled_for",
        ),
        Index(
            "ix_workspace_scheduled_task_runs_claimable",
            "status",
            "available_at",
        ),
        CheckConstraint(
            (
                "status IN ("
                "'queued', 'running', 'succeeded', 'partially_delivered', "
                "'delivery_failed', 'failed', 'waiting_confirmation'"
                ")"
            ),
            name="ck_workspace_scheduled_task_runs_status",
        ),
        CheckConstraint(
            "trigger_source IN ('scheduled', 'manual')",
            name="ck_workspace_scheduled_task_runs_trigger_source",
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
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_task_schedules.id", ondelete="SET NULL"),
        nullable=True,
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
    trigger_source: Mapped[str] = mapped_column(String(32), default="scheduled", nullable=False)
    status: Mapped[WorkspaceScheduledTaskRunStatus] = mapped_column(
        String(32),
        default=WorkspaceScheduledTaskRunStatus.QUEUED,
        nullable=False,
        index=True,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    delivery_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class WorkspaceScheduledTaskDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_scheduled_task_deliveries"
    __table_args__ = (
        CheckConstraint(
            "route_type IN ('chat', 'chat_provider')",
            name="ck_workspace_scheduled_task_deliveries_route_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="ck_workspace_scheduled_task_deliveries_status",
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
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_task_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_provider_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    route_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    external_thread_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[WorkspaceScheduledTaskDeliveryStatus] = mapped_column(
        String(32),
        default=WorkspaceScheduledTaskDeliveryStatus.PENDING,
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceScheduledTaskNotification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_scheduled_task_notifications"
    __table_args__ = (
        Index(
            "ix_workspace_scheduled_task_notifications_run_event",
            "task_run_id",
            "event_type",
        ),
        CheckConstraint(
            "event_type IN ('failure', 'waiting_approval', 'no_output', "
            "'delivery_failure', 'meaningful_update')",
            name="ck_workspace_scheduled_task_notifications_event_type",
        ),
        CheckConstraint(
            "route_type IN ('chat', 'chat_provider')",
            name="ck_workspace_scheduled_task_notifications_route_type",
        ),
        CheckConstraint(
            "status IN ('sent', 'failed', 'skipped')",
            name="ck_workspace_scheduled_task_notifications_status",
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
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_scheduled_task_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_provider_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[WorkspaceScheduledTaskNotificationEvent] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    route_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    external_thread_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[WorkspaceScheduledTaskNotificationStatus] = mapped_column(
        String(32),
        default=WorkspaceScheduledTaskNotificationStatus.SENT,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
