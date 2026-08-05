import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.schemas import APIModel

ScheduleEntryType = Literal["interval", "daily", "weekly", "weekdays", "monthly", "cron"]
ScheduleType = Literal[
    "manual",
    "interval",
    "daily",
    "weekly",
    "weekdays",
    "monthly",
    "cron",
    "multiple",
]
ConversationPolicy = Literal["reuse", "new_each_run"]
RouteType = Literal["chat", "chat_provider"]
NotificationEvent = Literal[
    "failure",
    "waiting_approval",
    "no_output",
    "delivery_failure",
    "meaningful_update",
]


class WorkspaceScheduledTaskNotificationRules(APIModel):
    on_failure: bool = True
    on_waiting_approval: bool = True
    on_no_output: bool = False
    on_delivery_failure: bool = True
    on_meaningful_update: bool = False


class WorkspaceScheduledTaskMonitoringStopConditions(APIModel):
    after_first_change: bool = False
    after_change_count: int | None = Field(default=None, ge=1, le=1000)
    after_run_count: int | None = Field(default=None, ge=1, le=10000)
    after_unchanged_count: int | None = Field(default=None, ge=1, le=10000)


class WorkspaceScheduledTaskMonitoringConfig(APIModel):
    enabled: bool = False
    notify_on_change: bool = True
    deliver_on_change_only: bool = True
    baseline_on_first_run: bool = True
    stop_conditions: WorkspaceScheduledTaskMonitoringStopConditions = Field(
        default_factory=WorkspaceScheduledTaskMonitoringStopConditions,
    )


class WorkspaceScheduledTaskOutputRoute(APIModel):
    route_type: RouteType
    connection_id: uuid.UUID | None = None
    external_thread_id: str = Field(default="", max_length=255)
    display_name: str = Field(default="", max_length=255)

    @field_validator("external_thread_id", "display_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_route(self) -> "WorkspaceScheduledTaskOutputRoute":
        if self.route_type == "chat_provider":
            if self.connection_id is None:
                raise ValueError("chat provider output requires a connection")
            if not self.external_thread_id:
                raise ValueError("chat provider output requires a conversation")
        return self


class WorkspaceScheduledTaskScheduleCreate(APIModel):
    name: str = Field(default="", max_length=120)
    schedule_type: ScheduleEntryType = "daily"
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("timezone")
    @classmethod
    def normalize_timezone_text(cls, value: str) -> str:
        return value.strip()


class WorkspaceScheduledTaskScheduleUpdate(WorkspaceScheduledTaskScheduleCreate):
    id: uuid.UUID | None = None


class WorkspaceScheduledTaskScheduleRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    name: str
    schedule_type: str
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool
    sort_order: int
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceScheduledTaskSchedulePreviewRequest(APIModel):
    schedules: list[WorkspaceScheduledTaskScheduleCreate] = Field(
        default_factory=list,
        max_length=12,
    )
    is_active: bool = True


class WorkspaceScheduledTaskSchedulePreviewResponse(APIModel):
    next_runs: list[datetime] = Field(default_factory=list)


class WorkspaceScheduledTaskCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=20000)
    schedule_type: ScheduleType = "daily"
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    schedules: list[WorkspaceScheduledTaskScheduleCreate] | None = Field(
        default=None,
        max_length=12,
    )
    output_routes: list[WorkspaceScheduledTaskOutputRoute] = Field(default_factory=list)
    notification_rules: WorkspaceScheduledTaskNotificationRules = Field(
        default_factory=WorkspaceScheduledTaskNotificationRules,
    )
    notification_routes: list[WorkspaceScheduledTaskOutputRoute] | None = Field(
        default=None,
        max_length=12,
    )
    approval_routes: list[WorkspaceScheduledTaskOutputRoute] | None = Field(
        default=None,
        max_length=12,
    )
    monitoring_config: WorkspaceScheduledTaskMonitoringConfig = Field(
        default_factory=WorkspaceScheduledTaskMonitoringConfig,
    )
    conversation_policy: ConversationPolicy = "reuse"
    is_active: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("instructions", "timezone")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()


class WorkspaceScheduledTaskUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = Field(default=None, min_length=1, max_length=20000)
    schedule_type: ScheduleType | None = None
    schedule_config: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    schedules: list[WorkspaceScheduledTaskScheduleUpdate] | None = Field(
        default=None,
        max_length=12,
    )
    output_routes: list[WorkspaceScheduledTaskOutputRoute] | None = None
    notification_rules: WorkspaceScheduledTaskNotificationRules | None = None
    notification_routes: list[WorkspaceScheduledTaskOutputRoute] | None = Field(
        default=None,
        max_length=12,
    )
    approval_routes: list[WorkspaceScheduledTaskOutputRoute] | None = Field(
        default=None,
        max_length=12,
    )
    monitoring_config: WorkspaceScheduledTaskMonitoringConfig | None = None
    reset_monitoring_state: bool = False
    conversation_policy: ConversationPolicy | None = None
    is_active: bool | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value is not None else None

    @field_validator("instructions", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class WorkspaceScheduledTaskDeliveryRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    task_run_id: uuid.UUID
    connection_id: uuid.UUID | None = None
    route_type: str
    provider: str
    external_thread_id: str
    display_name: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str
    retry_count: int = 0
    can_retry: bool = False
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceScheduledTaskNotificationRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    task_run_id: uuid.UUID
    connection_id: uuid.UUID | None = None
    event_type: str
    route_type: str
    provider: str
    external_thread_id: str
    display_name: str
    status: str
    title: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceScheduledTaskRunRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    task_id: uuid.UUID
    task_schedule_id: uuid.UUID | None = None
    agent_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    requested_by_id: uuid.UUID | None = None
    trigger_source: str
    status: str
    scheduled_for: datetime
    available_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int
    max_attempts: int
    error: str
    delivery_summary: dict[str, Any] = Field(default_factory=dict)
    deliveries: list[WorkspaceScheduledTaskDeliveryRead] = Field(default_factory=list)
    notifications: list[WorkspaceScheduledTaskNotificationRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkspaceScheduledTaskRouteTestRequest(APIModel):
    route: WorkspaceScheduledTaskOutputRoute
    message: str = Field(
        default="Wardn scheduled task route test.",
        min_length=1,
        max_length=2000,
    )

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()


class WorkspaceScheduledTaskRouteTestResponse(APIModel):
    route: WorkspaceScheduledTaskOutputRoute
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    sent_at: datetime | None = None


class WorkspaceScheduledTaskRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    created_by_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    last_task_run_id: uuid.UUID | None = None
    last_agent_run_id: uuid.UUID | None = None
    name: str
    instructions: str
    schedule_type: str
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str
    schedules: list[WorkspaceScheduledTaskScheduleRead] = Field(default_factory=list)
    next_run_preview: list[datetime] = Field(default_factory=list)
    output_routes: list[WorkspaceScheduledTaskOutputRoute] = Field(default_factory=list)
    notification_rules: WorkspaceScheduledTaskNotificationRules = Field(
        default_factory=WorkspaceScheduledTaskNotificationRules,
    )
    notification_routes: list[WorkspaceScheduledTaskOutputRoute] = Field(default_factory=list)
    approval_routes: list[WorkspaceScheduledTaskOutputRoute] = Field(default_factory=list)
    monitoring_config: WorkspaceScheduledTaskMonitoringConfig = Field(
        default_factory=WorkspaceScheduledTaskMonitoringConfig,
    )
    monitoring_status: str = "off"
    monitoring_state: dict[str, Any] = Field(default_factory=dict)
    conversation_policy: str
    is_active: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str
    last_error: str
    max_attempts: int
    created_at: datetime
    updated_at: datetime


class WorkspaceScheduledTaskListResponse(APIModel):
    tasks: list[WorkspaceScheduledTaskRead]


class WorkspaceScheduledTaskRunListResponse(APIModel):
    runs: list[WorkspaceScheduledTaskRunRead]
