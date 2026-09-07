import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class EventType(StrEnum):
    EXECUTION_STARTED = "execution.started"
    EXECUTION_PAUSED = "execution.paused"
    EXECUTION_RESUMED = "execution.resumed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_SUCCEEDED = "execution.succeeded"
    EXECUTION_CANCELLED = "execution.cancelled"
    USER_MESSAGE = "user.message"
    USER_FEEDBACK = "user.feedback"
    USER_CORRECTION = "user.correction"
    USER_PREFERENCE_EXPLICIT = "user.preference_explicit"
    AGENT_RESPONSE = "agent.response"
    AGENT_PLAN_CREATED = "agent.plan_created"
    AGENT_PLAN_UPDATED = "agent.plan_updated"
    AGENT_DECISION = "agent.decision"
    TOOL_SELECTED = "tool.selected"
    TOOL_CALL_STARTED = "tool.call_started"
    TOOL_CALL_COMPLETED = "tool.call_completed"
    TOOL_CALL_FAILED = "tool.call_failed"
    TOOL_RESULT_OBSERVED = "tool.result_observed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_EXPIRED = "approval.expired"
    SKILL_EXTERNAL_RETRIEVED = "skill.external_retrieved"


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    execution_kind: Literal["agent_run", "scheduled_run", "tool_invocation"]
    event_type: EventType
    source: Literal["agents", "mcp_runtime", "scheduled_tasks", "user"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    agent_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    objective_id: uuid.UUID | None = None
    scheduled_task_id: uuid.UUID | None = None
    scheduled_run_id: uuid.UUID | None = None
    parent_event_id: uuid.UUID | None = None
    tool_call_id: uuid.UUID | None = None
    trace_id: str = Field(default="", max_length=64, pattern=r"^[a-fA-F0-9]*$")
    span_id: str = Field(default="", max_length=32, pattern=r"^[a-fA-F0-9]*$")
    data: dict[str, Any] = Field(default_factory=dict)
    sensitive_paths: list[str] = Field(default_factory=list, exclude=True)
    occurred_at: AwareDatetime


class EventRead(EventCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: uuid.UUID
    sequence_number: int
    workspace_sequence: int
    created_at: datetime
