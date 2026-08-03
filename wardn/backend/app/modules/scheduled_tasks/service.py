import uuid
from datetime import UTC, datetime, time, timedelta
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
    WorkspaceScheduledTaskRun,
)
from app.modules.scheduled_tasks.schemas import (
    WorkspaceScheduledTaskCreate,
    WorkspaceScheduledTaskDeliveryRead,
    WorkspaceScheduledTaskListResponse,
    WorkspaceScheduledTaskOutputRoute,
    WorkspaceScheduledTaskRead,
    WorkspaceScheduledTaskRunListResponse,
    WorkspaceScheduledTaskRunRead,
    WorkspaceScheduledTaskUpdate,
)
from app.modules.users.models import User
from app.modules.users.repository import get_user_by_id

TASK_UNIQUE_CONSTRAINTS = {"uq_workspace_scheduled_tasks_workspace_name"}
DEFAULT_OUTPUT_ROUTES = [WorkspaceScheduledTaskOutputRoute(route_type="chat")]
SCHEDULED_AGENT_TRIGGER = "scheduled"
PROVIDER_EMPTY_REPLY = "The scheduled task completed, but the assistant did not return text."


def utc_now() -> datetime:
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def zoneinfo_for(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value.strip() or "UTC")
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
        scheduled_time = normalize_schedule_time(config_value(config, "time"))
        return {"time": scheduled_time.strftime("%H:%M")}
    if schedule_type == "weekly":
        scheduled_time = normalize_schedule_time(config_value(config, "time"))
        raw_weekday = config_value(config, "weekday")
        try:
            weekday = int(raw_weekday)
        except (TypeError, ValueError) as exc:
            raise InvalidScheduledTaskError("weekly schedule requires a weekday") from exc
        if not 0 <= weekday <= 6:
            raise InvalidScheduledTaskError("weekday must be between 0 and 6")
        return {"time": scheduled_time.strftime("%H:%M"), "weekday": weekday}
    raise InvalidScheduledTaskError("unsupported schedule type")


def next_run_at(
    *,
    schedule_type: str,
    schedule_config: dict[str, Any],
    timezone: str,
    after: datetime | None = None,
) -> datetime | None:
    if schedule_type == "manual":
        return None
    after = aware_utc(after or utc_now())
    zone = zoneinfo_for(timezone)
    local_after = after.astimezone(zone)
    if schedule_type == "interval":
        minutes = int(config_value(schedule_config, "everyMinutes", "every_minutes") or 0)
        if minutes < 1:
            raise InvalidScheduledTaskError("interval schedule requires minutes")
        return after + timedelta(minutes=minutes)

    scheduled_time = normalize_schedule_time(config_value(schedule_config, "time"))
    if schedule_type == "daily":
        candidate = datetime.combine(local_after.date(), scheduled_time, tzinfo=zone)
        if candidate <= local_after:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    if schedule_type == "weekly":
        weekday = int(config_value(schedule_config, "weekday"))
        days_until = (weekday - local_after.weekday()) % 7
        candidate_date = local_after.date() + timedelta(days=days_until)
        candidate = datetime.combine(candidate_date, scheduled_time, tzinfo=zone)
        if candidate <= local_after:
            candidate += timedelta(days=7)
        return candidate.astimezone(UTC)

    raise InvalidScheduledTaskError("unsupported schedule type")


def task_next_run_at(
    task: WorkspaceScheduledTask,
    *,
    after: datetime | None = None,
) -> datetime | None:
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


def route_reads(routes: list[dict[str, Any]] | None) -> list[WorkspaceScheduledTaskOutputRoute]:
    return [
        WorkspaceScheduledTaskOutputRoute.model_validate(route)
        for route in (routes or [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)])
    ]


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


def run_response(
    run: WorkspaceScheduledTaskRun,
    *,
    deliveries: list[WorkspaceScheduledTaskDelivery] | None = None,
) -> WorkspaceScheduledTaskRunRead:
    return WorkspaceScheduledTaskRunRead(
        id=run.id,
        organizationId=run.organization_id,
        workspaceId=run.workspace_id,
        taskId=run.task_id,
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
        createdAt=run.created_at,
        updatedAt=run.updated_at,
    )


def task_response(task: WorkspaceScheduledTask) -> WorkspaceScheduledTaskRead:
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
        outputRoutes=route_reads(task.output_routes),
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
    return WorkspaceScheduledTaskListResponse(tasks=[task_response(task) for task in tasks])


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
    return task_response(task)


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
    schedule_config = normalize_schedule_config(payload.schedule_type, payload.schedule_config)
    timezone = payload.timezone or "UTC"
    zoneinfo_for(timezone)
    routes = normalize_output_routes(payload.output_routes)
    await validate_output_routes(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        routes=routes,
    )
    next_at = (
        next_run_at(
            schedule_type=payload.schedule_type,
            schedule_config=schedule_config,
            timezone=timezone,
            after=utc_now(),
        )
        if payload.is_active
        else None
    )
    try:
        task = await repository.create_task(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent.id,
            created_by_id=user.id,
            name=payload.name,
            instructions=payload.instructions,
            schedule_type=payload.schedule_type,
            schedule_config=schedule_config,
            timezone=timezone,
            output_routes=routes,
            conversation_policy=payload.conversation_policy,
            is_active=payload.is_active,
            next_run_at=next_at,
            max_attempts=payload.max_attempts,
        )
    except IntegrityError as exc:
        if is_constraint_violation(exc, TASK_UNIQUE_CONSTRAINTS):
            raise DuplicateScheduledTaskError("scheduled task name already exists") from exc
        raise
    return task_response(task)


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

    schedule_changed = False
    if payload.name is not None:
        task.name = payload.name
    if payload.instructions is not None:
        task.instructions = payload.instructions
    if payload.schedule_type is not None:
        task.schedule_type = payload.schedule_type
        schedule_changed = True
    if payload.schedule_config is not None:
        schedule_changed = True
    if payload.timezone is not None:
        task.timezone = payload.timezone
        schedule_changed = True
    if payload.output_routes is not None:
        routes = normalize_output_routes(payload.output_routes)
        await validate_output_routes(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            routes=routes,
        )
        task.output_routes = routes
    if payload.conversation_policy is not None:
        task.conversation_policy = payload.conversation_policy
        if payload.conversation_policy == "new_each_run":
            task.conversation_id = None
    if payload.is_active is not None:
        task.is_active = payload.is_active
        schedule_changed = True
    if payload.max_attempts is not None:
        task.max_attempts = payload.max_attempts

    if schedule_changed:
        next_config = (
            payload.schedule_config
            if payload.schedule_config is not None
            else task.schedule_config
        )
        task.schedule_config = normalize_schedule_config(task.schedule_type, next_config)
        zoneinfo_for(task.timezone)
        task.next_run_at = (
            next_run_at(
                schedule_type=task.schedule_type,
                schedule_config=task.schedule_config,
                timezone=task.timezone,
                after=utc_now(),
            )
            if task.is_active
            else None
        )
    elif task.is_active and task.next_run_at is None:
        task.next_run_at = task_next_run_at(task, after=utc_now())

    try:
        await session.flush()
        await session.refresh(task)
    except IntegrityError as exc:
        if is_constraint_violation(exc, TASK_UNIQUE_CONSTRAINTS):
            raise DuplicateScheduledTaskError("scheduled task name already exists") from exc
        raise
    return task_response(task)


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
    return WorkspaceScheduledTaskRunListResponse(
        runs=[
            run_response(run, deliveries=deliveries_by_run.get(run.id, []))
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


async def reply_text_for_task_run(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    conversation_id: uuid.UUID,
) -> str:
    text = await chat_provider_service.latest_assistant_text(session, conversation_id)
    if text:
        return text
    approval = await agent_repository.latest_pending_tool_approval_by_conversation(
        session,
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        conversation_id=conversation_id,
    )
    if approval is not None:
        return chat_provider_service.approval_reply_text(approval)
    return PROVIDER_EMPTY_REPLY


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


async def deliver_task_run_output(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    conversation_id: uuid.UUID,
) -> dict[str, Any]:
    text = await reply_text_for_task_run(session, task=task, conversation_id=conversation_id)
    routes = task.output_routes or [DEFAULT_OUTPUT_ROUTES[0].model_dump(by_alias=False)]
    for route in routes:
        if route.get("route_type") == "chat_provider":
            await send_provider_delivery(session, task=task, run=run, route=route, text=text)
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
    delivery_summary = await deliver_task_run_output(
        session,
        task=task,
        run=run,
        conversation_id=conversation_id,
    )
    if status not in {"succeeded", "waiting_confirmation"}:
        status = "failed"
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
        next_run_for_task=lambda task, _scheduled_for: task_next_run_at(task, after=now),
    )
