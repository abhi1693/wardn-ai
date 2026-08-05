import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
from app.modules.agents import repository as agent_repository
from app.modules.agents import service as agent_service
from app.modules.agents.mappers import text_parts
from app.modules.agents.models import AgentRun, WorkspaceConversation
from app.modules.agents.schemas import AgentChatMessage, AgentChatRequest
from app.modules.chat_providers import repository as chat_provider_repository
from app.modules.chat_providers import service as chat_provider_service
from app.modules.chat_providers.models import ChatProviderConnection, ChatProviderEvent
from app.modules.organizations.service import require_workspace_admin, require_workspace_member
from app.modules.scheduled_tasks import repository
from app.modules.scheduled_tasks.exceptions import (
    DuplicateScheduledTaskError,
    InvalidScheduledTaskError,
    ScheduledTaskNotFoundError,
)
from app.modules.scheduled_tasks.models import (
    WorkspaceScheduledTask,
    WorkspaceScheduledTaskDelivery,
    WorkspaceScheduledTaskNotification,
    WorkspaceScheduledTaskRun,
    WorkspaceScheduledTaskSchedule,
)
from app.modules.scheduled_tasks.schemas import (
    WorkspaceScheduledTaskCreate,
    WorkspaceScheduledTaskDeliveryRead,
    WorkspaceScheduledTaskListResponse,
    WorkspaceScheduledTaskNotificationRead,
    WorkspaceScheduledTaskNotificationRules,
    WorkspaceScheduledTaskOutputRoute,
    WorkspaceScheduledTaskRead,
    WorkspaceScheduledTaskRunListResponse,
    WorkspaceScheduledTaskRunRead,
    WorkspaceScheduledTaskScheduleCreate,
    WorkspaceScheduledTaskSchedulePreviewRequest,
    WorkspaceScheduledTaskSchedulePreviewResponse,
    WorkspaceScheduledTaskScheduleRead,
    WorkspaceScheduledTaskScheduleUpdate,
    WorkspaceScheduledTaskUpdate,
)
from app.modules.users.models import User
from app.modules.users.repository import get_user_by_id

TASK_UNIQUE_CONSTRAINTS = {"uq_workspace_scheduled_tasks_workspace_name"}
DEFAULT_OUTPUT_ROUTES = [WorkspaceScheduledTaskOutputRoute(route_type="chat")]
SCHEDULED_AGENT_TRIGGER = "scheduled"
PROVIDER_EMPTY_REPLY = "The scheduled task completed, but the assistant did not return text."
DEFAULT_NOTIFICATION_RULES = WorkspaceScheduledTaskNotificationRules()
NOTIFICATION_EVENT_TO_RULE_KEY = {
    "failure": "on_failure",
    "waiting_approval": "on_waiting_approval",
    "no_output": "on_no_output",
    "delivery_failure": "on_delivery_failure",
    "meaningful_update": "on_meaningful_update",
}
ENTRY_SCHEDULE_TYPES = {"interval", "daily", "weekly", "weekdays", "monthly", "cron"}
MAX_SCHEDULES_PER_TASK = 12
MAX_TIMES_PER_SCHEDULE = 12
MAX_VALUES_PER_SCHEDULE = 31
MAX_LOOKAHEAD_DAYS = 366 * 5
TIMEZONE_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
}


def delivery_summary_count(delivery_summary: Mapping[str, Any], key: str) -> int:
    value = delivery_summary.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        try:
            return max(0, int(value))
        except ValueError:
            return 0
    return 0


def scheduled_task_run_status(agent_status: str, delivery_summary: Mapping[str, Any]) -> str:
    if agent_status == "waiting_confirmation":
        return "waiting_confirmation"
    if agent_status != "succeeded":
        return "failed"
    failed = delivery_summary_count(delivery_summary, "failed")
    if failed <= 0:
        return "succeeded"
    sent = delivery_summary_count(delivery_summary, "sent")
    if sent > 0:
        return "partially_delivered"
    return "delivery_failed"


@dataclass(frozen=True)
class ScheduleSpec:
    schedule_type: str
    schedule_config: dict[str, Any]
    timezone: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True


@dataclass(frozen=True)
class TaskRunReply:
    text: str
    kind: str
    approval_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CronExpression:
    minutes: set[int]
    hours: set[int]
    month_days: set[int]
    months: set[int]
    weekdays: set[int]
    month_day_restricted: bool
    weekday_restricted: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_timezone(value: str) -> str:
    timezone = (value or "").strip() or "UTC"
    return TIMEZONE_ALIASES.get(timezone, timezone)


def zoneinfo_for(value: str) -> ZoneInfo:
    timezone = normalize_timezone(value)
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise InvalidScheduledTaskError("invalid task timezone") from exc


def config_value(config: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in config:
            return config[key]
    return None


def normalize_schedule_time(value: Any) -> time:
    if not isinstance(value, str):
        raise InvalidScheduledTaskError("schedule time must use HH:MM")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise InvalidScheduledTaskError("schedule time must use HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise InvalidScheduledTaskError("schedule time must use HH:MM") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise InvalidScheduledTaskError("schedule time must use HH:MM")
    return time(hour=hour, minute=minute)


def normalize_schedule_times(config: dict[str, Any]) -> list[str]:
    raw_times = config_value(config, "times")
    if raw_times is None:
        raw_times = config_value(config, "time")
    if isinstance(raw_times, str):
        candidates: list[Any] = [raw_times]
    elif isinstance(raw_times, list):
        candidates = raw_times
    else:
        raise InvalidScheduledTaskError("schedule requires at least one run time")
    times = sorted({normalize_schedule_time(value).strftime("%H:%M") for value in candidates})
    if not times:
        raise InvalidScheduledTaskError("schedule requires at least one run time")
    if len(times) > MAX_TIMES_PER_SCHEDULE:
        raise InvalidScheduledTaskError("a schedule can have at most 12 run times")
    return times


def normalize_integer_values(
    config: dict[str, Any],
    *,
    plural_key: str,
    singular_key: str | None,
    minimum: int,
    maximum: int,
    label: str,
    default: Sequence[int] | None = None,
) -> list[int]:
    raw_values = config_value(config, plural_key)
    if raw_values is None and singular_key is not None:
        raw_values = config_value(config, singular_key)
    if raw_values is None and default is not None:
        raw_values = list(default)
    if isinstance(raw_values, list):
        candidates: list[Any] = raw_values
    elif raw_values is None:
        raise InvalidScheduledTaskError(f"{label} is required")
    else:
        candidates = [raw_values]
    values: set[int] = set()
    for raw_value in candidates:
        if isinstance(raw_value, bool):
            raise InvalidScheduledTaskError(f"{label} must be a number")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise InvalidScheduledTaskError(f"{label} must be a number") from exc
        if not minimum <= value <= maximum:
            raise InvalidScheduledTaskError(f"{label} must be between {minimum} and {maximum}")
        values.add(value)
    if not values:
        raise InvalidScheduledTaskError(f"{label} is required")
    if len(values) > MAX_VALUES_PER_SCHEDULE:
        raise InvalidScheduledTaskError(f"{label} has too many values")
    return sorted(values)


def parse_cron_field(
    raw_field: str,
    *,
    minimum: int,
    maximum: int,
    label: str,
    allow_question: bool = False,
) -> tuple[set[int], bool]:
    field = raw_field.strip()
    unrestricted_tokens = {"*"} | ({"?"} if allow_question else set())
    if field in unrestricted_tokens:
        return set(range(minimum, maximum + 1)), False

    values: set[int] = set()
    restricted = False
    for token in field.split(","):
        token = token.strip()
        if not token:
            raise InvalidScheduledTaskError("cron expression has an empty field")
        if "/" in token:
            base, raw_step = token.split("/", 1)
            try:
                step = int(raw_step)
            except ValueError as exc:
                raise InvalidScheduledTaskError("cron step must be a number") from exc
            if step < 1:
                raise InvalidScheduledTaskError("cron step must be at least 1")
        else:
            base = token
            step = 1

        if base in unrestricted_tokens:
            start = minimum
            end = maximum
            restricted = restricted or step != 1
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            try:
                start = int(raw_start)
                end = int(raw_end)
            except ValueError as exc:
                raise InvalidScheduledTaskError(f"cron {label} range must be numeric") from exc
            restricted = True
        else:
            try:
                start = int(base)
            except ValueError as exc:
                raise InvalidScheduledTaskError(f"cron {label} must be numeric") from exc
            end = start
            restricted = True

        if start > end:
            raise InvalidScheduledTaskError(f"cron {label} range is invalid")
        if start < minimum or end > maximum:
            raise InvalidScheduledTaskError(
                f"cron {label} must be between {minimum} and {maximum}"
            )
        values.update(range(start, end + 1, step))

    if not values:
        raise InvalidScheduledTaskError(f"cron {label} has no values")
    return values, restricted


def parse_cron_expression(expression: str) -> CronExpression:
    parts = expression.split()
    if len(parts) != 5:
        raise InvalidScheduledTaskError("cron expression must have 5 fields")
    minutes, _ = parse_cron_field(parts[0], minimum=0, maximum=59, label="minute")
    hours, _ = parse_cron_field(parts[1], minimum=0, maximum=23, label="hour")
    month_days, month_day_restricted = parse_cron_field(
        parts[2],
        minimum=1,
        maximum=31,
        label="day of month",
        allow_question=True,
    )
    months, _ = parse_cron_field(parts[3], minimum=1, maximum=12, label="month")
    raw_weekdays, weekday_restricted = parse_cron_field(
        parts[4],
        minimum=0,
        maximum=7,
        label="day of week",
        allow_question=True,
    )
    weekdays = {6 if value in {0, 7} else value - 1 for value in raw_weekdays}
    return CronExpression(
        minutes=minutes,
        hours=hours,
        month_days=month_days,
        months=months,
        weekdays=weekdays,
        month_day_restricted=month_day_restricted,
        weekday_restricted=weekday_restricted,
    )


def normalize_cron_expression(value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidScheduledTaskError("cron schedule requires an expression")
    expression = " ".join(value.strip().split())
    if not expression:
        raise InvalidScheduledTaskError("cron schedule requires an expression")
    parse_cron_expression(expression)
    return expression


def normalize_schedule_config(schedule_type: str, config: dict[str, Any]) -> dict[str, Any]:
    if schedule_type == "manual":
        return {}
    if schedule_type == "interval":
        raw_minutes = config_value(config, "everyMinutes", "every_minutes")
        try:
            minutes = int(raw_minutes)
        except (TypeError, ValueError) as exc:
            raise InvalidScheduledTaskError("interval schedule requires minutes") from exc
        if not 1 <= minutes <= 10_080:
            raise InvalidScheduledTaskError("interval minutes must be between 1 and 10080")
        return {"everyMinutes": minutes}
    if schedule_type == "daily":
        return {"times": normalize_schedule_times(config)}
    if schedule_type == "weekly":
        return {
            "times": normalize_schedule_times(config),
            "weekdays": normalize_integer_values(
                config,
                plural_key="weekdays",
                singular_key="weekday",
                minimum=0,
                maximum=6,
                label="weekday",
            ),
        }
    if schedule_type == "weekdays":
        return {"times": normalize_schedule_times(config), "weekdays": [0, 1, 2, 3, 4]}
    if schedule_type == "monthly":
        return {
            "times": normalize_schedule_times(config),
            "monthDays": normalize_integer_values(
                config,
                plural_key="monthDays",
                singular_key="monthDay",
                minimum=1,
                maximum=31,
                label="month day",
            ),
        }
    if schedule_type == "cron":
        return {"expression": normalize_cron_expression(config_value(config, "expression", "cron"))}
    raise InvalidScheduledTaskError("unsupported schedule type")


def next_calendar_run_at(
    *,
    schedule_type: str,
    schedule_config: dict[str, Any],
    timezone: str,
    after: datetime | None = None,
) -> datetime | None:
    after = aware_utc(after or utc_now())
    zone = zoneinfo_for(timezone)
    local_after = after.astimezone(zone)
    times = [normalize_schedule_time(value) for value in normalize_schedule_times(schedule_config)]
    weekdays = (
        set(
            normalize_integer_values(
                schedule_config,
                plural_key="weekdays",
                singular_key="weekday",
                minimum=0,
                maximum=6,
                label="weekday",
            )
        )
        if schedule_type == "weekly"
        else set()
    )
    month_days = (
        set(
            normalize_integer_values(
                schedule_config,
                plural_key="monthDays",
                singular_key="monthDay",
                minimum=1,
                maximum=31,
                label="month day",
            )
        )
        if schedule_type == "monthly"
        else set()
    )
    start_date = local_after.date()
    for day_offset in range(MAX_LOOKAHEAD_DAYS + 1):
        candidate_date = start_date + timedelta(days=day_offset)
        if schedule_type == "weekly" and candidate_date.weekday() not in weekdays:
            continue
        if schedule_type == "weekdays" and candidate_date.weekday() not in {0, 1, 2, 3, 4}:
            continue
        if schedule_type == "monthly" and candidate_date.day not in month_days:
            continue
        for scheduled_time in times:
            candidate = datetime.combine(candidate_date, scheduled_time, tzinfo=zone)
            if candidate > local_after:
                return candidate.astimezone(UTC)
    return None


def next_cron_run_at(
    *,
    expression: str,
    timezone: str,
    after: datetime | None = None,
) -> datetime | None:
    cron = parse_cron_expression(expression)
    after = aware_utc(after or utc_now())
    zone = zoneinfo_for(timezone)
    local_after = after.astimezone(zone)
    start_date = local_after.date()
    for day_offset in range(MAX_LOOKAHEAD_DAYS + 1):
        candidate_date = start_date + timedelta(days=day_offset)
        if candidate_date.month not in cron.months:
            continue
        month_day_matches = candidate_date.day in cron.month_days
        weekday_matches = candidate_date.weekday() in cron.weekdays
        if cron.month_day_restricted and cron.weekday_restricted:
            if not (month_day_matches or weekday_matches):
                continue
        elif not month_day_matches or not weekday_matches:
            continue
        for hour in sorted(cron.hours):
            for minute in sorted(cron.minutes):
                candidate = datetime.combine(
                    candidate_date,
                    time(hour=hour, minute=minute),
                    tzinfo=zone,
                )
                if candidate > local_after:
                    return candidate.astimezone(UTC)
    return None


def next_run_at(
    *,
    schedule_type: str,
    schedule_config: dict[str, Any],
    timezone: str,
    after: datetime | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> datetime | None:
    if schedule_type == "manual":
        return None
    after = aware_utc(after or utc_now())
    starts_at = aware_utc(starts_at) if starts_at is not None else None
    ends_at = aware_utc(ends_at) if ends_at is not None else None
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise InvalidScheduledTaskError("schedule end must be after the start")
    if ends_at is not None and after >= ends_at:
        return None
    zoneinfo_for(timezone)
    search_after = after
    if starts_at is not None and after < starts_at:
        search_after = starts_at - timedelta(seconds=1)

    if schedule_type == "interval":
        minutes = int(config_value(schedule_config, "everyMinutes", "every_minutes") or 0)
        if minutes < 1:
            raise InvalidScheduledTaskError("interval schedule requires minutes")
        candidate = (
            starts_at
            if starts_at is not None and after < starts_at
            else after + timedelta(minutes=minutes)
        )
        return candidate if ends_at is None or candidate <= ends_at else None

    if schedule_type in {"daily", "weekly", "weekdays", "monthly"}:
        candidate = next_calendar_run_at(
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            timezone=timezone,
            after=search_after,
        )
        if candidate is None or (ends_at is not None and candidate > ends_at):
            return None
        return candidate

    if schedule_type == "cron":
        candidate = next_cron_run_at(
            expression=str(config_value(schedule_config, "expression") or ""),
            timezone=timezone,
            after=search_after,
        )
        if candidate is None or (ends_at is not None and candidate > ends_at):
            return None
        return candidate

    raise InvalidScheduledTaskError("unsupported schedule type")


def schedule_spec_next_run_at(
    spec: ScheduleSpec,
    *,
    after: datetime | None = None,
) -> datetime | None:
    if not spec.is_active:
        return None
    return next_run_at(
        schedule_type=spec.schedule_type,
        schedule_config=spec.schedule_config,
        timezone=spec.timezone,
        after=after,
        starts_at=spec.starts_at,
        ends_at=spec.ends_at,
    )


def schedule_model_spec(schedule: WorkspaceScheduledTaskSchedule) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_type=schedule.schedule_type,
        schedule_config=schedule.schedule_config or {},
        timezone=schedule.timezone,
        starts_at=schedule.starts_at,
        ends_at=schedule.ends_at,
        is_active=schedule.is_active,
    )


def next_runs_preview(
    specs: Sequence[ScheduleSpec],
    *,
    after: datetime | None = None,
    limit: int = 5,
) -> list[datetime]:
    if limit < 1:
        return []
    cursors: dict[int, datetime] = {}
    base_after = aware_utc(after or utc_now())
    for index, spec in enumerate(specs):
        candidate = schedule_spec_next_run_at(spec, after=base_after)
        if candidate is not None:
            cursors[index] = candidate
    preview: list[datetime] = []
    while cursors and len(preview) < limit:
        index, candidate = min(cursors.items(), key=lambda item: (item[1], item[0]))
        preview.append(candidate)
        next_candidate = schedule_spec_next_run_at(specs[index], after=candidate)
        if next_candidate is None:
            del cursors[index]
        else:
            cursors[index] = next_candidate
    return preview


def task_next_run_at(
    task: WorkspaceScheduledTask,
    *,
    after: datetime | None = None,
) -> datetime | None:
    if task.schedule_type == "multiple":
        return task.next_run_at
    return next_run_at(
        schedule_type=task.schedule_type,
        schedule_config=task.schedule_config or {},
        timezone=task.timezone,
        after=after,
    )


def normalize_output_routes(
    routes: list[WorkspaceScheduledTaskOutputRoute] | None,
) -> list[dict[str, Any]]:
    normalized_routes = routes or DEFAULT_OUTPUT_ROUTES
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for route in normalized_routes:
        payload = route.model_dump(by_alias=False)
        route_type = payload["route_type"]
        connection_id = payload.get("connection_id")
        external_thread_id = str(payload.get("external_thread_id") or "").strip()
        key = (route_type, str(connection_id or ""), external_thread_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "route_type": route_type,
                "connection_id": str(connection_id) if connection_id else None,
                "external_thread_id": external_thread_id,
                "display_name": str(payload.get("display_name") or "").strip(),
            }
        )
    if not deduped:
        return [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)]
    return deduped


def normalize_route_payloads(
    routes: list[WorkspaceScheduledTaskOutputRoute] | None,
    *,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if routes is None:
        return list(fallback or [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)])
    return normalize_output_routes(routes)


def route_reads(routes: list[dict[str, Any]] | None) -> list[WorkspaceScheduledTaskOutputRoute]:
    return [
        WorkspaceScheduledTaskOutputRoute.model_validate(route)
        for route in (routes or [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)])
    ]


def normalize_notification_rules(
    rules: WorkspaceScheduledTaskNotificationRules | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if rules is None:
        return DEFAULT_NOTIFICATION_RULES.model_dump(by_alias=False)
    if isinstance(rules, WorkspaceScheduledTaskNotificationRules):
        return rules.model_dump(by_alias=False)
    return WorkspaceScheduledTaskNotificationRules.model_validate(rules).model_dump(
        by_alias=False
    )


def notification_rule_enabled(
    rules: Mapping[str, Any] | None,
    event_type: str,
) -> bool:
    key = NOTIFICATION_EVENT_TO_RULE_KEY[event_type]
    normalized = normalize_notification_rules(rules)
    return bool(normalized.get(key))


def normalized_output_text(text: str) -> str:
    return " ".join(text.casefold().split())


def output_text_hash(text: str) -> str:
    return sha256(normalized_output_text(text).encode("utf-8")).hexdigest()


def output_text_preview(text: str, *, limit: int = 500) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 12].rstrip() + " [truncated]"


def reply_summary(reply: TaskRunReply) -> dict[str, Any]:
    text = reply.text.strip()
    has_assistant_output = reply.kind == "assistant" and bool(text)
    return {
        "outputKind": reply.kind,
        "hasOutput": has_assistant_output,
        "outputHash": output_text_hash(text) if has_assistant_output else "",
        "outputPreview": output_text_preview(text)
        if reply.kind in {"assistant", "approval"} and text
        else "",
        "approvalId": str(reply.approval_id) if reply.approval_id else "",
    }


def schedule_response(
    schedule: WorkspaceScheduledTaskSchedule,
) -> WorkspaceScheduledTaskScheduleRead:
    return WorkspaceScheduledTaskScheduleRead(
        id=schedule.id,
        taskId=schedule.task_id,
        name=schedule.name,
        scheduleType=schedule.schedule_type,
        scheduleConfig=schedule.schedule_config,
        timezone=schedule.timezone,
        startsAt=schedule.starts_at,
        endsAt=schedule.ends_at,
        isActive=schedule.is_active,
        sortOrder=schedule.sort_order,
        nextRunAt=schedule.next_run_at,
        createdAt=schedule.created_at,
        updatedAt=schedule.updated_at,
    )


def normalize_schedule_window(
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    starts_at = aware_utc(starts_at) if starts_at is not None else None
    ends_at = aware_utc(ends_at) if ends_at is not None else None
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise InvalidScheduledTaskError("schedule end must be after the start")
    return starts_at, ends_at


def normalize_schedule_entry_payload(
    entry: WorkspaceScheduledTaskScheduleCreate | WorkspaceScheduledTaskScheduleUpdate,
    *,
    default_timezone: str,
) -> dict[str, Any]:
    if entry.schedule_type not in ENTRY_SCHEDULE_TYPES:
        raise InvalidScheduledTaskError("unsupported schedule type")
    timezone = normalize_timezone(entry.timezone or default_timezone or "UTC")
    zoneinfo_for(timezone)
    starts_at, ends_at = normalize_schedule_window(entry.starts_at, entry.ends_at)
    schedule_config = normalize_schedule_config(entry.schedule_type, entry.schedule_config or {})
    return {
        "name": entry.name,
        "schedule_type": entry.schedule_type,
        "schedule_config": schedule_config,
        "timezone": timezone,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_active": entry.is_active,
    }


def schedule_payload_spec(payload: dict[str, Any]) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_type=payload["schedule_type"],
        schedule_config=payload["schedule_config"],
        timezone=payload["timezone"],
        starts_at=payload["starts_at"],
        ends_at=payload["ends_at"],
        is_active=payload["is_active"],
    )


def legacy_payload_schedules(
    *,
    schedule_type: str,
    schedule_config: dict[str, Any],
    timezone: str,
) -> list[WorkspaceScheduledTaskScheduleCreate]:
    if schedule_type == "manual":
        return []
    if schedule_type == "multiple":
        raise InvalidScheduledTaskError("multiple schedules must be edited with schedule rows")
    if schedule_type not in ENTRY_SCHEDULE_TYPES:
        raise InvalidScheduledTaskError("unsupported schedule type")
    return [
        WorkspaceScheduledTaskScheduleCreate(
            scheduleType=schedule_type,
            scheduleConfig=schedule_config or {},
            timezone=timezone or "UTC",
        )
    ]


def create_payload_schedules(
    payload: WorkspaceScheduledTaskCreate,
) -> list[WorkspaceScheduledTaskScheduleCreate]:
    if payload.schedules is not None:
        return payload.schedules
    return legacy_payload_schedules(
        schedule_type=payload.schedule_type,
        schedule_config=payload.schedule_config,
        timezone=payload.timezone,
    )


def update_payload_replaces_schedules(payload: WorkspaceScheduledTaskUpdate) -> bool:
    return (
        payload.schedules is not None
        or payload.schedule_type is not None
        or payload.schedule_config is not None
    )


def update_payload_schedules(
    payload: WorkspaceScheduledTaskUpdate,
    task: WorkspaceScheduledTask,
) -> list[WorkspaceScheduledTaskScheduleUpdate | WorkspaceScheduledTaskScheduleCreate]:
    if payload.schedules is not None:
        return payload.schedules
    return legacy_payload_schedules(
        schedule_type=payload.schedule_type or task.schedule_type,
        schedule_config=(
            payload.schedule_config
            if payload.schedule_config is not None
            else task.schedule_config
        ),
        timezone=payload.timezone or task.timezone,
    )


def schedule_summary(schedule: WorkspaceScheduledTaskSchedule) -> dict[str, Any]:
    return {
        "id": str(schedule.id),
        "name": schedule.name,
        "scheduleType": schedule.schedule_type,
        "scheduleConfig": schedule.schedule_config,
        "timezone": schedule.timezone,
        "isActive": schedule.is_active,
    }


def apply_task_schedule_summary(
    task: WorkspaceScheduledTask,
    schedules: Sequence[WorkspaceScheduledTaskSchedule],
) -> None:
    ordered_schedules = sorted(schedules, key=lambda item: (item.sort_order, str(item.id)))
    active_next_runs = [
        schedule.next_run_at
        for schedule in ordered_schedules
        if schedule.is_active and schedule.next_run_at is not None
    ]
    task.next_run_at = min(active_next_runs) if task.is_active and active_next_runs else None
    if not ordered_schedules:
        task.schedule_type = "manual"
        task.schedule_config = {}
        return
    if len(ordered_schedules) == 1:
        schedule = ordered_schedules[0]
        task.schedule_type = schedule.schedule_type
        task.schedule_config = schedule.schedule_config
        task.timezone = schedule.timezone
        return
    task.schedule_type = "multiple"
    task.schedule_config = {
        "schedules": [schedule_summary(schedule) for schedule in ordered_schedules]
    }
    task.timezone = ordered_schedules[0].timezone


async def sync_task_schedules(
    session: AsyncSession,
    task: WorkspaceScheduledTask,
    entries: Sequence[WorkspaceScheduledTaskScheduleCreate | WorkspaceScheduledTaskScheduleUpdate],
    *,
    now: datetime,
) -> list[WorkspaceScheduledTaskSchedule]:
    if len(entries) > MAX_SCHEDULES_PER_TASK:
        raise InvalidScheduledTaskError("a task can have at most 12 schedules")
    existing = await repository.list_task_schedules(session, task_id=task.id, for_update=True)
    existing_by_id = {schedule.id: schedule for schedule in existing}
    seen_ids: set[uuid.UUID] = set()
    schedules: list[WorkspaceScheduledTaskSchedule] = []
    for sort_order, entry in enumerate(entries):
        entry_id = entry.id if isinstance(entry, WorkspaceScheduledTaskScheduleUpdate) else None
        if entry_id is not None:
            if entry_id in seen_ids:
                raise InvalidScheduledTaskError("schedule rows must not be duplicated")
            schedule = existing_by_id.get(entry_id)
            if schedule is None:
                raise InvalidScheduledTaskError("schedule row does not belong to this task")
            seen_ids.add(entry_id)
        else:
            schedule = WorkspaceScheduledTaskSchedule(
                organization_id=task.organization_id,
                workspace_id=task.workspace_id,
                task_id=task.id,
            )
            session.add(schedule)
        normalized = normalize_schedule_entry_payload(entry, default_timezone=task.timezone)
        schedule.name = normalized["name"]
        schedule.schedule_type = normalized["schedule_type"]
        schedule.schedule_config = normalized["schedule_config"]
        schedule.timezone = normalized["timezone"]
        schedule.starts_at = normalized["starts_at"]
        schedule.ends_at = normalized["ends_at"]
        schedule.is_active = normalized["is_active"]
        schedule.sort_order = sort_order
        spec = schedule_payload_spec(normalized)
        schedule.next_run_at = (
            schedule_spec_next_run_at(spec, after=now)
            if task.is_active and schedule.is_active
            else None
        )
        schedules.append(schedule)

    for schedule in existing:
        if schedule.id not in seen_ids and schedule not in schedules:
            await session.delete(schedule)

    await session.flush()
    apply_task_schedule_summary(task, schedules)
    await session.flush()
    return schedules


async def refresh_task_schedules_next_runs(
    session: AsyncSession,
    task: WorkspaceScheduledTask,
    *,
    now: datetime,
) -> list[WorkspaceScheduledTaskSchedule]:
    schedules = await repository.list_task_schedules(session, task_id=task.id, for_update=True)
    for schedule in schedules:
        schedule.next_run_at = (
            schedule_spec_next_run_at(schedule_model_spec(schedule), after=now)
            if task.is_active and schedule.is_active
            else None
        )
    await session.flush()
    apply_task_schedule_summary(task, schedules)
    await session.flush()
    return schedules


async def validate_output_routes(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    routes: list[dict[str, Any]],
) -> None:
    for route in routes:
        if route.get("route_type") != "chat_provider":
            continue
        connection_id = route.get("connection_id")
        try:
            connection_uuid = uuid.UUID(str(connection_id))
        except (TypeError, ValueError) as exc:
            raise InvalidScheduledTaskError(
                "chat provider route has an invalid connection"
            ) from exc
        connection = await chat_provider_repository.get_connection(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            connection_id=connection_uuid,
        )
        if connection is None or not connection.is_active:
            raise InvalidScheduledTaskError("chat provider route is not active")
        thread_id = str(route.get("external_thread_id") or "").strip()
        if not thread_id:
            raise InvalidScheduledTaskError("chat provider route requires a conversation")


def delivery_response(
    delivery: WorkspaceScheduledTaskDelivery,
) -> WorkspaceScheduledTaskDeliveryRead:
    return WorkspaceScheduledTaskDeliveryRead(
        id=delivery.id,
        taskId=delivery.task_id,
        taskRunId=delivery.task_run_id,
        connectionId=delivery.connection_id,
        routeType=delivery.route_type,
        provider=delivery.provider,
        externalThreadId=delivery.external_thread_id,
        displayName=delivery.display_name,
        status=delivery.status,
        payload=delivery.payload,
        error=delivery.error,
        deliveredAt=delivery.delivered_at,
        createdAt=delivery.created_at,
        updatedAt=delivery.updated_at,
    )


def notification_response(
    notification: WorkspaceScheduledTaskNotification,
) -> WorkspaceScheduledTaskNotificationRead:
    return WorkspaceScheduledTaskNotificationRead(
        id=notification.id,
        taskId=notification.task_id,
        taskRunId=notification.task_run_id,
        connectionId=notification.connection_id,
        eventType=notification.event_type,
        routeType=notification.route_type,
        provider=notification.provider,
        externalThreadId=notification.external_thread_id,
        displayName=notification.display_name,
        status=notification.status,
        title=notification.title,
        message=notification.message,
        payload=notification.payload,
        error=notification.error,
        deliveredAt=notification.delivered_at,
        createdAt=notification.created_at,
        updatedAt=notification.updated_at,
    )


def run_response(
    run: WorkspaceScheduledTaskRun,
    *,
    deliveries: list[WorkspaceScheduledTaskDelivery] | None = None,
    notifications: list[WorkspaceScheduledTaskNotification] | None = None,
) -> WorkspaceScheduledTaskRunRead:
    return WorkspaceScheduledTaskRunRead(
        id=run.id,
        organizationId=run.organization_id,
        workspaceId=run.workspace_id,
        taskId=run.task_id,
        taskScheduleId=run.task_schedule_id,
        agentId=run.agent_id,
        conversationId=run.conversation_id,
        agentRunId=run.agent_run_id,
        requestedById=run.requested_by_id,
        triggerSource=run.trigger_source,
        status=run.status,
        scheduledFor=run.scheduled_for,
        availableAt=run.available_at,
        startedAt=run.started_at,
        finishedAt=run.finished_at,
        attemptCount=run.attempt_count,
        maxAttempts=run.max_attempts,
        error=run.error,
        deliverySummary=run.delivery_summary,
        deliveries=[delivery_response(delivery) for delivery in (deliveries or [])],
        notifications=[
            notification_response(notification) for notification in (notifications or [])
        ],
        createdAt=run.created_at,
        updatedAt=run.updated_at,
    )


def task_response(
    task: WorkspaceScheduledTask,
    *,
    schedules: Sequence[WorkspaceScheduledTaskSchedule] | None = None,
) -> WorkspaceScheduledTaskRead:
    schedule_rows = list(schedules or [])
    preview = (
        next_runs_preview(
            [schedule_model_spec(schedule) for schedule in schedule_rows],
            after=utc_now(),
            limit=5,
        )
        if task.is_active
        else []
    )
    return WorkspaceScheduledTaskRead(
        id=task.id,
        organizationId=task.organization_id,
        workspaceId=task.workspace_id,
        agentId=task.agent_id,
        createdById=task.created_by_id,
        conversationId=task.conversation_id,
        lastTaskRunId=task.last_task_run_id,
        lastAgentRunId=task.last_agent_run_id,
        name=task.name,
        instructions=task.instructions,
        scheduleType=task.schedule_type,
        scheduleConfig=task.schedule_config,
        timezone=task.timezone,
        schedules=[schedule_response(schedule) for schedule in schedule_rows],
        nextRunPreview=preview,
        outputRoutes=route_reads(task.output_routes),
        notificationRules=WorkspaceScheduledTaskNotificationRules.model_validate(
            normalize_notification_rules(task.notification_rules)
        ),
        notificationRoutes=route_reads(task.notification_routes),
        approvalRoutes=route_reads(task.approval_routes),
        conversationPolicy=task.conversation_policy,
        isActive=task.is_active,
        nextRunAt=task.next_run_at,
        lastRunAt=task.last_run_at,
        lastStatus=task.last_status,
        lastError=task.last_error,
        maxAttempts=task.max_attempts,
        createdAt=task.created_at,
        updatedAt=task.updated_at,
    )


async def list_workspace_scheduled_tasks(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> WorkspaceScheduledTaskListResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    tasks = await repository.list_tasks(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    schedules_by_task = await repository.list_task_schedules_for_tasks(
        session,
        task_ids=[task.id for task in tasks],
    )
    return WorkspaceScheduledTaskListResponse(
        tasks=[
            task_response(task, schedules=schedules_by_task.get(task.id, []))
            for task in tasks
        ]
    )


async def get_workspace_scheduled_task(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> WorkspaceScheduledTaskRead:
    await require_workspace_member(session, user, organization_id, workspace_id)
    task = await repository.get_task(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
    )
    if task is None:
        raise ScheduledTaskNotFoundError("scheduled task not found")
    schedules = await repository.list_task_schedules(session, task_id=task.id)
    return task_response(task, schedules=schedules)


async def preview_workspace_scheduled_task_schedules(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: WorkspaceScheduledTaskSchedulePreviewRequest,
) -> WorkspaceScheduledTaskSchedulePreviewResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    if not payload.is_active:
        return WorkspaceScheduledTaskSchedulePreviewResponse(nextRuns=[])
    specs = [
        schedule_payload_spec(normalize_schedule_entry_payload(entry, default_timezone="UTC"))
        for entry in payload.schedules
    ]
    return WorkspaceScheduledTaskSchedulePreviewResponse(
        nextRuns=next_runs_preview(specs, after=utc_now(), limit=5)
    )


async def create_workspace_scheduled_task(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: WorkspaceScheduledTaskCreate,
) -> WorkspaceScheduledTaskRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    agent = await agent_service.ensure_workspace_assistant_agent(
        session,
        user,
        organization_id,
        workspace_id,
    )
    timezone = normalize_timezone(payload.timezone or "UTC")
    zoneinfo_for(timezone)
    schedule_entries = create_payload_schedules(payload)
    routes = normalize_output_routes(payload.output_routes)
    notification_routes = normalize_route_payloads(payload.notification_routes, fallback=routes)
    approval_routes = normalize_route_payloads(
        payload.approval_routes,
        fallback=notification_routes,
    )
    notification_rules = normalize_notification_rules(payload.notification_rules)
    await validate_output_routes(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        routes=routes,
    )
    await validate_output_routes(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        routes=notification_routes,
    )
    await validate_output_routes(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        routes=approval_routes,
    )
    now = utc_now()
    try:
        task = await repository.create_task(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent.id,
            created_by_id=user.id,
            name=payload.name,
            instructions=payload.instructions,
            schedule_type="manual",
            schedule_config={},
            timezone=timezone,
            output_routes=routes,
            notification_rules=notification_rules,
            notification_routes=notification_routes,
            approval_routes=approval_routes,
            conversation_policy=payload.conversation_policy,
            is_active=payload.is_active,
            next_run_at=None,
            max_attempts=payload.max_attempts,
        )
        schedules = await sync_task_schedules(session, task, schedule_entries, now=now)
    except IntegrityError as exc:
        if is_constraint_violation(exc, TASK_UNIQUE_CONSTRAINTS):
            raise DuplicateScheduledTaskError("scheduled task name already exists") from exc
        raise
    return task_response(task, schedules=schedules)


async def update_workspace_scheduled_task(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: WorkspaceScheduledTaskUpdate,
) -> WorkspaceScheduledTaskRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    task = await repository.get_task(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
    )
    if task is None:
        raise ScheduledTaskNotFoundError("scheduled task not found")

    schedule_replaced = update_payload_replaces_schedules(payload)
    schedules: list[WorkspaceScheduledTaskSchedule] | None = None
    if payload.name is not None:
        task.name = payload.name
    if payload.instructions is not None:
        task.instructions = payload.instructions
    if payload.timezone is not None:
        task.timezone = normalize_timezone(payload.timezone)
        zoneinfo_for(task.timezone)
    if payload.output_routes is not None:
        routes = normalize_output_routes(payload.output_routes)
        await validate_output_routes(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            routes=routes,
        )
        task.output_routes = routes
    if payload.notification_rules is not None:
        task.notification_rules = normalize_notification_rules(payload.notification_rules)
    if payload.notification_routes is not None:
        notification_routes = normalize_route_payloads(payload.notification_routes)
        await validate_output_routes(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            routes=notification_routes,
        )
        task.notification_routes = notification_routes
    if payload.approval_routes is not None:
        approval_routes = normalize_route_payloads(payload.approval_routes)
        await validate_output_routes(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            routes=approval_routes,
        )
        task.approval_routes = approval_routes
    if payload.conversation_policy is not None:
        task.conversation_policy = payload.conversation_policy
        if payload.conversation_policy == "new_each_run":
            task.conversation_id = None
    if payload.is_active is not None:
        task.is_active = payload.is_active
    if payload.max_attempts is not None:
        task.max_attempts = payload.max_attempts

    try:
        now = utc_now()
        if schedule_replaced:
            schedules = await sync_task_schedules(
                session,
                task,
                update_payload_schedules(payload, task),
                now=now,
            )
        elif payload.is_active is not None:
            schedules = await refresh_task_schedules_next_runs(session, task, now=now)
        await session.flush()
        await session.refresh(task)
        if schedules is None:
            schedules = await repository.list_task_schedules(session, task_id=task.id)
        elif schedule_replaced or payload.is_active is not None:
            schedules = await repository.list_task_schedules(session, task_id=task.id)
    except IntegrityError as exc:
        if is_constraint_violation(exc, TASK_UNIQUE_CONSTRAINTS):
            raise DuplicateScheduledTaskError("scheduled task name already exists") from exc
        raise
    return task_response(task, schedules=schedules)


async def delete_workspace_scheduled_task(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> None:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    task = await repository.get_task(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
    )
    if task is None:
        raise ScheduledTaskNotFoundError("scheduled task not found")
    await repository.delete_task(session, task)


async def enqueue_workspace_scheduled_task_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> WorkspaceScheduledTaskRunRead:
    await require_workspace_admin(session, user, organization_id, workspace_id)
    task = await repository.get_task(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
    )
    if task is None:
        raise ScheduledTaskNotFoundError("scheduled task not found")
    now = utc_now()
    run = await repository.create_task_run(
        session,
        task=task,
        scheduled_for=now,
        available_at=now,
        trigger_source="manual",
        requested_by_id=user.id,
    )
    return run_response(run)


async def list_workspace_scheduled_task_runs(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    *,
    limit: int = 50,
) -> WorkspaceScheduledTaskRunListResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    runs = await repository.list_task_runs(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
        limit=limit,
    )
    deliveries_by_run = await repository.list_run_deliveries(
        session,
        run_ids=[run.id for run in runs],
    )
    notifications_by_run = await repository.list_run_notifications(
        session,
        run_ids=[run.id for run in runs],
    )
    return WorkspaceScheduledTaskRunListResponse(
        runs=[
            run_response(
                run,
                deliveries=deliveries_by_run.get(run.id, []),
                notifications=notifications_by_run.get(run.id, []),
            )
            for run in runs
        ]
    )


async def latest_scheduled_agent_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> AgentRun | None:
    result = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.workspace_id == workspace_id,
            AgentRun.conversation_id == conversation_id,
            AgentRun.trigger_type == SCHEDULED_AGENT_TRIGGER,
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ensure_task_conversation(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    actor: User,
) -> WorkspaceConversation:
    conversation = None
    if task.conversation_policy == "reuse" and task.conversation_id is not None:
        conversation = await agent_repository.get_workspace_conversation(
            session,
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            conversation_id=task.conversation_id,
        )
    if conversation is not None and conversation.agent_id == task.agent_id:
        return conversation
    conversation = await agent_repository.create_workspace_conversation(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        agent_id=task.agent_id,
        created_by_id=actor.id,
        title=f"Scheduled: {task.name}"[:200],
    )
    if task.conversation_policy == "reuse":
        task.conversation_id = conversation.id
    return conversation


def scheduled_task_prompt(task: WorkspaceScheduledTask, run: WorkspaceScheduledTaskRun) -> str:
    local_time = run.scheduled_for.astimezone(zoneinfo_for(task.timezone))
    return (
        f"Scheduled task: {task.name}\n"
        f"Scheduled for: {local_time.isoformat()}\n"
        f"Workspace ID: {task.workspace_id}\n\n"
        "Instructions:\n"
        f"{task.instructions.strip()}\n\n"
        "Produce the final answer as a clear message that can be delivered to the selected "
        "workspace chat output channels."
    )


async def resolve_task_actor(
    session: AsyncSession,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
) -> User:
    actor_id = run.requested_by_id or task.created_by_id
    if actor_id is None:
        raise InvalidScheduledTaskError("scheduled task has no run actor")
    actor = await get_user_by_id(session, actor_id)
    if actor is None or not actor.is_active:
        raise InvalidScheduledTaskError("scheduled task actor is inactive")
    return actor


async def prepare_agent_run_for_task(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    actor: User,
    session_factory,
) -> tuple[uuid.UUID, uuid.UUID, Any]:
    conversation = await ensure_task_conversation(session, task=task, actor=actor)
    run.conversation_id = conversation.id
    stream = await agent_service.stream_agent_chat(
        session,
        actor,
        task.organization_id,
        task.agent_id,
        AgentChatRequest(
            id=str(conversation.id),
            messages=[
                AgentChatMessage(
                    role="user",
                    parts=text_parts(scheduled_task_prompt(task, run)),
                )
            ],
        ),
        workspace_id=task.workspace_id,
        session_factory=session_factory,
        trigger_type=SCHEDULED_AGENT_TRIGGER,
    )
    agent_run = await latest_scheduled_agent_run(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        conversation_id=conversation.id,
    )
    if agent_run is not None:
        run.agent_run_id = agent_run.id
    await session.flush()
    return conversation.id, agent_run.id if agent_run is not None else None, stream


async def reply_for_task_run(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    conversation_id: uuid.UUID,
) -> TaskRunReply:
    text = await chat_provider_service.latest_assistant_text(session, conversation_id)
    if text:
        return TaskRunReply(text=text, kind="assistant")
    approval = await agent_repository.latest_pending_tool_approval_by_conversation(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        conversation_id=conversation_id,
    )
    if approval is not None:
        return TaskRunReply(
            text=chat_provider_service.approval_reply_text(approval),
            kind="approval",
            approval_id=approval.id,
        )
    return TaskRunReply(text=PROVIDER_EMPTY_REPLY, kind="empty")


async def provider_route_connection(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    route: dict[str, Any],
) -> ChatProviderConnection | None:
    connection_id = route.get("connection_id")
    if not connection_id:
        return None
    try:
        connection_uuid = uuid.UUID(str(connection_id))
    except ValueError:
        return None
    return await chat_provider_repository.get_connection(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        connection_id=connection_uuid,
    )


async def record_chat_delivery(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    conversation_id: uuid.UUID,
) -> None:
    await repository.add_delivery(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        task_run_id=run.id,
        route_type="chat",
        status="sent",
        payload={"conversationId": str(conversation_id)},
        delivered_at=utc_now(),
    )


async def send_provider_delivery(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    route: dict[str, Any],
    text: str,
) -> None:
    now = utc_now()
    connection = await provider_route_connection(session, task=task, route=route)
    external_thread_id = str(route.get("external_thread_id") or "").strip()
    display_name = str(route.get("display_name") or "").strip()
    if connection is None or not connection.is_active:
        await repository.add_delivery(
            session,
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_run_id=run.id,
            route_type="chat_provider",
            status="failed",
            provider=str(route.get("provider") or ""),
            external_thread_id=external_thread_id,
            display_name=display_name,
            error="Chat provider connection is not active.",
        )
        return
    try:
        payload = await chat_provider_service.send_provider_text_message(
            session,
            connection,
            external_thread_id=external_thread_id,
            text=text,
        )
    except Exception as exc:
        await repository.add_delivery(
            session,
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_run_id=run.id,
            route_type="chat_provider",
            status="failed",
            connection_id=connection.id,
            provider=connection.provider,
            external_thread_id=external_thread_id,
            display_name=display_name,
            error=str(exc),
        )
        return
    outbound_message_id = chat_provider_service.provider_response_message_id(connection, payload)
    session.add(
        ChatProviderEvent(
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            connection_id=connection.id,
            conversation_id=run.conversation_id,
            provider=connection.provider,
            external_event_id=outbound_message_id or f"scheduled:{run.id}:{external_thread_id}",
            direction="outbound",
            event_type="message.text",
            status="sent",
            payload={connection.provider: payload, "scheduledTaskRunId": str(run.id)},
            processed_at=now,
        )
    )
    await repository.add_delivery(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        task_run_id=run.id,
        route_type="chat_provider",
        status="sent",
        connection_id=connection.id,
        provider=connection.provider,
        external_thread_id=external_thread_id,
        display_name=display_name,
        payload={connection.provider: payload},
        delivered_at=now,
    )


async def record_chat_notification(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    event_type: str,
    title: str,
    message: str,
) -> None:
    now = utc_now()
    if run.conversation_id is None:
        await repository.add_notification(
            session,
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_run_id=run.id,
            event_type=event_type,
            route_type="chat",
            status="skipped",
            title=title,
            message=message,
            error="Scheduled task run has no conversation.",
        )
        return
    await agent_repository.append_conversation_message(
        session,
        conversation_id=run.conversation_id,
        role="assistant",
        content=message,
        parts=text_parts(message),
        agent_run_id=run.agent_run_id,
    )
    await repository.add_notification(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        task_run_id=run.id,
        event_type=event_type,
        route_type="chat",
        status="sent",
        title=title,
        message=message,
        payload={"conversationId": str(run.conversation_id)},
        delivered_at=now,
    )


async def send_provider_notification(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    event_type: str,
    route: dict[str, Any],
    title: str,
    message: str,
) -> None:
    now = utc_now()
    connection = await provider_route_connection(session, task=task, route=route)
    external_thread_id = str(route.get("external_thread_id") or "").strip()
    display_name = str(route.get("display_name") or "").strip()
    if connection is None or not connection.is_active:
        await repository.add_notification(
            session,
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_run_id=run.id,
            event_type=event_type,
            route_type="chat_provider",
            status="failed",
            provider=str(route.get("provider") or ""),
            external_thread_id=external_thread_id,
            display_name=display_name,
            title=title,
            message=message,
            error="Chat provider connection is not active.",
        )
        return
    try:
        payload = await chat_provider_service.send_provider_text_message(
            session,
            connection,
            external_thread_id=external_thread_id,
            text=message,
        )
    except Exception as exc:
        await repository.add_notification(
            session,
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_run_id=run.id,
            event_type=event_type,
            route_type="chat_provider",
            status="failed",
            connection_id=connection.id,
            provider=connection.provider,
            external_thread_id=external_thread_id,
            display_name=display_name,
            title=title,
            message=message,
            error=str(exc),
        )
        return
    outbound_message_id = chat_provider_service.provider_response_message_id(connection, payload)
    session.add(
        ChatProviderEvent(
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            connection_id=connection.id,
            conversation_id=run.conversation_id,
            provider=connection.provider,
            external_event_id=outbound_message_id
            or f"scheduled-notification:{run.id}:{event_type}:{external_thread_id}",
            direction="outbound",
            event_type="scheduled_task.notification",
            status="sent",
            payload={connection.provider: payload, "scheduledTaskRunId": str(run.id)},
            processed_at=now,
        )
    )
    await repository.add_notification(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        task_run_id=run.id,
        event_type=event_type,
        route_type="chat_provider",
        status="sent",
        connection_id=connection.id,
        provider=connection.provider,
        external_thread_id=external_thread_id,
        display_name=display_name,
        title=title,
        message=message,
        payload={connection.provider: payload},
        delivered_at=now,
    )


async def send_task_notification(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    event_type: str,
    title: str,
    message: str,
    routes: Sequence[dict[str, Any]],
) -> None:
    for route in routes:
        if route.get("route_type") == "chat_provider":
            await send_provider_notification(
                session,
                task=task,
                run=run,
                event_type=event_type,
                route=route,
                title=title,
                message=message,
            )
        else:
            await record_chat_notification(
                session,
                task=task,
                run=run,
                event_type=event_type,
                title=title,
                message=message,
            )


def notification_title(event_type: str) -> str:
    if event_type == "failure":
        return "Scheduled task failed"
    if event_type == "waiting_approval":
        return "Scheduled task needs approval"
    if event_type == "no_output":
        return "Scheduled task had no output"
    if event_type == "delivery_failure":
        return "Scheduled task delivery failed"
    if event_type == "meaningful_update":
        return "Scheduled task found an update"
    return "Scheduled task notification"


def notification_message(
    *,
    event_type: str,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    error: str,
    delivery_summary: Mapping[str, Any],
) -> str:
    if event_type == "waiting_approval":
        approval_text = str(delivery_summary.get("outputPreview") or "").strip()
        if approval_text:
            return approval_text
        approval_id = str(delivery_summary.get("approvalId") or "").strip()
        suffix = f"\n\nApproval ID: {approval_id}" if approval_id else ""
        return f"{task.name} is waiting for tool approval before it can continue.{suffix}"
    if event_type == "failure":
        reason = error.strip() or "The assistant run failed."
        return (
            f"{task.name} failed for the run scheduled at "
            f"{run.scheduled_for.isoformat()}.\n\n{reason}"
        )
    if event_type == "no_output":
        return f"{task.name} completed, but the assistant did not return text."
    if event_type == "delivery_failure":
        sent = delivery_summary_count(delivery_summary, "sent")
        failed = delivery_summary_count(delivery_summary, "failed")
        return f"{task.name} had output delivery failures. Sent: {sent}. Failed: {failed}."
    if event_type == "meaningful_update":
        preview = str(delivery_summary.get("outputPreview") or "").strip()
        if preview:
            return f"{task.name} found a meaningful update.\n\n{preview}"
        return f"{task.name} found a meaningful update."
    return f"{task.name} has a scheduled task notification."


def notification_events_for_run(
    *,
    task: WorkspaceScheduledTask,
    status: str,
    delivery_summary: Mapping[str, Any],
) -> list[str]:
    events: list[str] = []
    if status == "failed" and notification_rule_enabled(task.notification_rules, "failure"):
        events.append("failure")
    if status == "waiting_confirmation" and notification_rule_enabled(
        task.notification_rules,
        "waiting_approval",
    ):
        events.append("waiting_approval")
    if delivery_summary.get("outputKind") == "empty" and notification_rule_enabled(
        task.notification_rules,
        "no_output",
    ):
        events.append("no_output")
    if delivery_summary_count(delivery_summary, "failed") > 0 and notification_rule_enabled(
        task.notification_rules,
        "delivery_failure",
    ):
        events.append("delivery_failure")
    if notification_rule_enabled(task.notification_rules, "meaningful_update"):
        output_hash = str(delivery_summary.get("outputHash") or "").strip()
        if output_hash:
            state = task.notification_state or {}
            previous_hash = str(state.get("lastMeaningfulOutputHash") or "")
            if previous_hash != output_hash:
                events.append("meaningful_update")
            task.notification_state = {
                **state,
                "lastMeaningfulOutputHash": output_hash,
                "lastMeaningfulOutputAt": utc_now().isoformat(),
            }
    return events


async def dispatch_task_run_notifications(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    status: str,
    error: str,
    delivery_summary: Mapping[str, Any],
) -> None:
    events = notification_events_for_run(
        task=task,
        status=status,
        delivery_summary=delivery_summary,
    )
    for event_type in events:
        routes = (
            task.approval_routes
            if event_type == "waiting_approval"
            else task.notification_routes
        )
        await send_task_notification(
            session,
            task=task,
            run=run,
            event_type=event_type,
            title=notification_title(event_type),
            message=notification_message(
                event_type=event_type,
                task=task,
                run=run,
                error=error,
                delivery_summary=delivery_summary,
            ),
            routes=routes or [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)],
        )


async def deliver_task_run_output(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    conversation_id: uuid.UUID,
) -> dict[str, Any]:
    reply = await reply_for_task_run(session, task=task, conversation_id=conversation_id)
    routes = task.output_routes or [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)]
    for route in routes:
        if route.get("route_type") == "chat_provider":
            await send_provider_delivery(
                session,
                task=task,
                run=run,
                route=route,
                text=reply.text,
            )
        else:
            await record_chat_delivery(
                session,
                task=task,
                run=run,
                conversation_id=conversation_id,
            )
    deliveries = await repository.list_run_deliveries(session, run_ids=[run.id])
    run_deliveries = deliveries.get(run.id, [])
    return {
        "total": len(run_deliveries),
        "sent": sum(1 for delivery in run_deliveries if delivery.status == "sent"),
        "failed": sum(1 for delivery in run_deliveries if delivery.status == "failed"),
        **reply_summary(reply),
    }


async def execute_claimed_task_run(
    session: AsyncSession,
    *,
    run: WorkspaceScheduledTaskRun,
    worker_id: str,
    session_factory,
) -> None:
    task = await repository.get_task(
        session,
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        task_id=run.task_id,
    )
    if task is None:
        raise ScheduledTaskNotFoundError("scheduled task not found")
    actor = await resolve_task_actor(session, task, run)
    conversation_id, agent_run_id, stream = await prepare_agent_run_for_task(
        session,
        task=task,
        run=run,
        actor=actor,
        session_factory=session_factory,
    )
    await session.commit()
    async for _chunk in stream:
        pass

    task = await repository.get_task(
        session,
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        task_id=run.task_id,
    )
    if task is None:
        raise ScheduledTaskNotFoundError("scheduled task not found")
    agent_run = await session.get(AgentRun, agent_run_id) if agent_run_id else None
    if agent_run is not None:
        await session.refresh(agent_run)
    if agent_run is not None:
        status = (
            "waiting_confirmation"
            if agent_run.status == "waiting_confirmation"
            else agent_run.status
        )
        error = agent_run.error
    else:
        status = "failed"
        error = "Scheduled task did not create an agent run."
    if status == "waiting_confirmation":
        delivery_summary = {
            "total": 0,
            "sent": 0,
            "failed": 0,
            **reply_summary(
                await reply_for_task_run(
                    session,
                    task=task,
                    conversation_id=conversation_id,
                )
            ),
        }
    else:
        delivery_summary = await deliver_task_run_output(
            session,
            task=task,
            run=run,
            conversation_id=conversation_id,
        )
    status = scheduled_task_run_status(status, delivery_summary)
    completed = await repository.complete_run(
        session,
        run.id,
        worker_id=worker_id,
        now=utc_now(),
        status=status,
        error=error,
        agent_run_id=agent_run_id,
        conversation_id=conversation_id,
        delivery_summary=delivery_summary,
    )
    if not completed:
        raise InvalidScheduledTaskError("scheduled task run lease was lost")
    await dispatch_task_run_notifications(
        session,
        task=task,
        run=run,
        status=status,
        error=error,
        delivery_summary=delivery_summary,
    )


async def enqueue_due_task_runs(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 25,
) -> int:
    return await repository.enqueue_due_runs(
        session,
        now=now,
        limit=limit,
        next_run_for_schedule=lambda schedule, scheduled_for: schedule_spec_next_run_at(
            schedule_model_spec(schedule),
            after=scheduled_for,
        ),
    )
