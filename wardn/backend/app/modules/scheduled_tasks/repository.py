import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.scheduled_tasks.models import (
    WorkspaceScheduledTask,
    WorkspaceScheduledTaskDelivery,
    WorkspaceScheduledTaskNotification,
    WorkspaceScheduledTaskRun,
    WorkspaceScheduledTaskSchedule,
)

ACTIVE_RUN_STATUSES = ("queued", "running", "waiting_confirmation")


async def list_tasks(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[WorkspaceScheduledTask]:
    result = await session.execute(
        select(WorkspaceScheduledTask)
        .where(
            WorkspaceScheduledTask.organization_id == organization_id,
            WorkspaceScheduledTask.workspace_id == workspace_id,
        )
        .order_by(
            WorkspaceScheduledTask.is_active.desc(),
            WorkspaceScheduledTask.next_run_at.asc().nulls_last(),
            WorkspaceScheduledTask.created_at.desc(),
            WorkspaceScheduledTask.id.desc(),
        )
    )
    return list(result.scalars().all())


async def get_task(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> WorkspaceScheduledTask | None:
    result = await session.execute(
        select(WorkspaceScheduledTask).where(
            WorkspaceScheduledTask.id == task_id,
            WorkspaceScheduledTask.organization_id == organization_id,
            WorkspaceScheduledTask.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def get_task_by_name(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    name: str,
) -> WorkspaceScheduledTask | None:
    result = await session.execute(
        select(WorkspaceScheduledTask).where(
            WorkspaceScheduledTask.workspace_id == workspace_id,
            WorkspaceScheduledTask.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_task_schedules(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    for_update: bool = False,
) -> list[WorkspaceScheduledTaskSchedule]:
    statement = (
        select(WorkspaceScheduledTaskSchedule)
        .where(WorkspaceScheduledTaskSchedule.task_id == task_id)
        .order_by(
            WorkspaceScheduledTaskSchedule.sort_order.asc(),
            WorkspaceScheduledTaskSchedule.created_at.asc(),
            WorkspaceScheduledTaskSchedule.id.asc(),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_task_schedules_for_tasks(
    session: AsyncSession,
    *,
    task_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[WorkspaceScheduledTaskSchedule]]:
    if not task_ids:
        return {}
    result = await session.execute(
        select(WorkspaceScheduledTaskSchedule)
        .where(WorkspaceScheduledTaskSchedule.task_id.in_(task_ids))
        .order_by(
            WorkspaceScheduledTaskSchedule.task_id.asc(),
            WorkspaceScheduledTaskSchedule.sort_order.asc(),
            WorkspaceScheduledTaskSchedule.created_at.asc(),
            WorkspaceScheduledTaskSchedule.id.asc(),
        )
    )
    schedules_by_task: dict[uuid.UUID, list[WorkspaceScheduledTaskSchedule]] = {}
    for schedule in result.scalars().all():
        schedules_by_task.setdefault(schedule.task_id, []).append(schedule)
    return schedules_by_task


async def get_due_task_schedule(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    now: datetime,
) -> WorkspaceScheduledTaskSchedule | None:
    result = await session.execute(
        select(WorkspaceScheduledTaskSchedule)
        .where(
            WorkspaceScheduledTaskSchedule.task_id == task_id,
            WorkspaceScheduledTaskSchedule.is_active.is_(True),
            WorkspaceScheduledTaskSchedule.next_run_at.is_not(None),
            WorkspaceScheduledTaskSchedule.next_run_at <= now,
        )
        .order_by(
            WorkspaceScheduledTaskSchedule.next_run_at.asc(),
            WorkspaceScheduledTaskSchedule.sort_order.asc(),
            WorkspaceScheduledTaskSchedule.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


async def first_task_schedule_next_run(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
) -> datetime | None:
    result = await session.execute(
        select(WorkspaceScheduledTaskSchedule.next_run_at)
        .where(
            WorkspaceScheduledTaskSchedule.task_id == task_id,
            WorkspaceScheduledTaskSchedule.is_active.is_(True),
            WorkspaceScheduledTaskSchedule.next_run_at.is_not(None),
        )
        .order_by(
            WorkspaceScheduledTaskSchedule.next_run_at.asc(),
            WorkspaceScheduledTaskSchedule.sort_order.asc(),
            WorkspaceScheduledTaskSchedule.id.asc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_task(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    created_by_id: uuid.UUID | None,
    name: str,
    instructions: str,
    schedule_type: str,
    schedule_config: dict,
    timezone: str,
    output_routes: list[dict],
    notification_rules: dict,
    notification_routes: list[dict],
    approval_routes: list[dict],
    monitoring_config: dict,
    monitoring_status: str,
    conversation_policy: str,
    is_active: bool,
    next_run_at: datetime | None,
    max_attempts: int,
) -> WorkspaceScheduledTask:
    task = WorkspaceScheduledTask(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        created_by_id=created_by_id,
        name=name,
        instructions=instructions,
        schedule_type=schedule_type,
        schedule_config=schedule_config,
        timezone=timezone,
        output_routes=output_routes,
        notification_rules=notification_rules,
        notification_routes=notification_routes,
        approval_routes=approval_routes,
        monitoring_config=monitoring_config,
        monitoring_status=monitoring_status,
        notification_state={},
        conversation_policy=conversation_policy,
        is_active=is_active,
        next_run_at=next_run_at if is_active else None,
        last_status="",
        last_error="",
        max_attempts=max_attempts,
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task: WorkspaceScheduledTask) -> None:
    await session.delete(task)
    await session.flush()


async def list_task_runs(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[WorkspaceScheduledTaskRun]:
    statement = select(WorkspaceScheduledTaskRun).where(
        WorkspaceScheduledTaskRun.organization_id == organization_id,
        WorkspaceScheduledTaskRun.workspace_id == workspace_id,
    )
    if task_id is not None:
        statement = statement.where(WorkspaceScheduledTaskRun.task_id == task_id)
    result = await session.execute(
        statement.order_by(
            WorkspaceScheduledTaskRun.scheduled_for.desc(),
            WorkspaceScheduledTaskRun.created_at.desc(),
            WorkspaceScheduledTaskRun.id.desc(),
        ).limit(limit)
    )
    return list(result.scalars().all())


async def get_task_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    for_update: bool = False,
) -> WorkspaceScheduledTaskRun | None:
    statement = select(WorkspaceScheduledTaskRun).where(
        WorkspaceScheduledTaskRun.id == run_id,
        WorkspaceScheduledTaskRun.organization_id == organization_id,
        WorkspaceScheduledTaskRun.workspace_id == workspace_id,
        WorkspaceScheduledTaskRun.task_id == task_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_run(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    for_update: bool = False,
) -> WorkspaceScheduledTaskRun | None:
    statement = select(WorkspaceScheduledTaskRun).where(
        WorkspaceScheduledTaskRun.id == run_id,
        WorkspaceScheduledTaskRun.organization_id == organization_id,
        WorkspaceScheduledTaskRun.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_delivery(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    task_run_id: uuid.UUID,
    delivery_id: uuid.UUID,
    for_update: bool = False,
) -> WorkspaceScheduledTaskDelivery | None:
    statement = select(WorkspaceScheduledTaskDelivery).where(
        WorkspaceScheduledTaskDelivery.id == delivery_id,
        WorkspaceScheduledTaskDelivery.organization_id == organization_id,
        WorkspaceScheduledTaskDelivery.workspace_id == workspace_id,
        WorkspaceScheduledTaskDelivery.task_id == task_id,
        WorkspaceScheduledTaskDelivery.task_run_id == task_run_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_run_deliveries(
    session: AsyncSession,
    *,
    run_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[WorkspaceScheduledTaskDelivery]]:
    if not run_ids:
        return {}
    result = await session.execute(
        select(WorkspaceScheduledTaskDelivery)
        .where(WorkspaceScheduledTaskDelivery.task_run_id.in_(run_ids))
        .order_by(
            WorkspaceScheduledTaskDelivery.created_at.asc(),
            WorkspaceScheduledTaskDelivery.id.asc(),
        )
    )
    deliveries: dict[uuid.UUID, list[WorkspaceScheduledTaskDelivery]] = {}
    for delivery in result.scalars().all():
        deliveries.setdefault(delivery.task_run_id, []).append(delivery)
    return deliveries


async def list_run_notifications(
    session: AsyncSession,
    *,
    run_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[WorkspaceScheduledTaskNotification]]:
    if not run_ids:
        return {}
    result = await session.execute(
        select(WorkspaceScheduledTaskNotification)
        .where(WorkspaceScheduledTaskNotification.task_run_id.in_(run_ids))
        .order_by(
            WorkspaceScheduledTaskNotification.created_at.asc(),
            WorkspaceScheduledTaskNotification.id.asc(),
        )
    )
    notifications: dict[uuid.UUID, list[WorkspaceScheduledTaskNotification]] = {}
    for notification in result.scalars().all():
        notifications.setdefault(notification.task_run_id, []).append(notification)
    return notifications


def task_has_active_run_condition(candidate) -> Any:
    active_run = aliased(WorkspaceScheduledTaskRun)
    return exists(
        select(active_run.id).where(
            active_run.task_id == candidate.id,
            active_run.status.in_(ACTIVE_RUN_STATUSES),
        )
    ).correlate(candidate)


def due_task_statement(now: datetime, *, limit: int = 25):
    candidate = aliased(WorkspaceScheduledTask)
    return (
        select(candidate)
        .where(
            candidate.is_active.is_(True),
            candidate.schedule_type != "manual",
            candidate.next_run_at.is_not(None),
            candidate.next_run_at <= now,
            ~task_has_active_run_condition(candidate),
        )
        .order_by(candidate.next_run_at.asc(), candidate.created_at.asc(), candidate.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


async def enqueue_due_runs(
    session: AsyncSession,
    *,
    now: datetime,
    next_run_for_schedule,
    limit: int = 25,
) -> int:
    result = await session.execute(due_task_statement(now, limit=limit))
    tasks = list(result.scalars().all())
    enqueued = 0
    for task in tasks:
        schedule = await get_due_task_schedule(session, task_id=task.id, now=now)
        if schedule is None:
            task.next_run_at = await first_task_schedule_next_run(session, task_id=task.id)
            continue
        scheduled_for = schedule.next_run_at or task.next_run_at or now
        run = WorkspaceScheduledTaskRun(
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            task_schedule_id=schedule.id,
            agent_id=task.agent_id,
            requested_by_id=task.created_by_id,
            trigger_source="scheduled",
            status="queued",
            scheduled_for=scheduled_for,
            available_at=now,
            attempt_count=0,
            max_attempts=task.max_attempts,
            error="",
            delivery_summary={},
        )
        session.add(run)
        task.last_run_at = now
        task.last_status = "queued"
        task.last_error = ""
        schedule.next_run_at = next_run_for_schedule(schedule, scheduled_for)
        await session.flush()
        task.next_run_at = await first_task_schedule_next_run(session, task_id=task.id)
        enqueued += 1
    await session.flush()
    return enqueued


async def create_task_run(
    session: AsyncSession,
    *,
    task: WorkspaceScheduledTask,
    scheduled_for: datetime,
    available_at: datetime,
    trigger_source: str,
    requested_by_id: uuid.UUID | None,
    task_schedule_id: uuid.UUID | None = None,
) -> WorkspaceScheduledTaskRun:
    run = WorkspaceScheduledTaskRun(
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        task_schedule_id=task_schedule_id,
        agent_id=task.agent_id,
        requested_by_id=requested_by_id,
        trigger_source=trigger_source,
        status="queued",
        scheduled_for=scheduled_for,
        available_at=available_at,
        attempt_count=0,
        max_attempts=task.max_attempts,
        error="",
        delivery_summary={},
    )
    session.add(run)
    task.last_run_at = available_at
    task.last_status = "queued"
    task.last_error = ""
    await session.flush()
    await session.refresh(run)
    return run


def claimable_run_statement(now: datetime):
    candidate = aliased(WorkspaceScheduledTaskRun)
    blocker = aliased(WorkspaceScheduledTaskRun)
    earlier_active_run = exists(
        select(blocker.id).where(
            blocker.task_id == candidate.task_id,
            blocker.status.in_(ACTIVE_RUN_STATUSES),
            or_(
                blocker.scheduled_for < candidate.scheduled_for,
                and_(
                    blocker.scheduled_for == candidate.scheduled_for,
                    blocker.id < candidate.id,
                ),
            ),
        )
    ).correlate(candidate)
    return (
        select(candidate)
        .where(
            candidate.status == "queued",
            candidate.available_at <= now,
            ~earlier_active_run,
        )
        .order_by(candidate.available_at.asc(), candidate.scheduled_for.asc(), candidate.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def claim_next_run(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> WorkspaceScheduledTaskRun | None:
    result = await session.execute(claimable_run_statement(now))
    run = result.scalar_one_or_none()
    if run is None:
        return None
    run.status = "running"
    run.worker_id = worker_id
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    run.attempt_count += 1
    run.started_at = run.started_at or now
    run.error = ""
    await session.flush()
    return run


async def heartbeat_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    worker_id: str,
    lease_expires_at: datetime,
) -> bool:
    result = await session.execute(
        update(WorkspaceScheduledTaskRun)
        .where(
            WorkspaceScheduledTaskRun.id == run_id,
            WorkspaceScheduledTaskRun.status == "running",
            WorkspaceScheduledTaskRun.worker_id == worker_id,
        )
        .values(lease_expires_at=lease_expires_at)
    )
    return result.rowcount == 1


async def get_owned_running_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    worker_id: str,
) -> WorkspaceScheduledTaskRun | None:
    result = await session.execute(
        select(WorkspaceScheduledTaskRun)
        .where(
            WorkspaceScheduledTaskRun.id == run_id,
            WorkspaceScheduledTaskRun.status == "running",
            WorkspaceScheduledTaskRun.worker_id == worker_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def complete_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    worker_id: str,
    now: datetime,
    status: str,
    error: str,
    agent_run_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    delivery_summary: dict,
) -> bool:
    run = await get_owned_running_run(session, run_id, worker_id=worker_id)
    if run is None:
        return False
    run.status = status
    run.error = error
    run.finished_at = now
    run.worker_id = ""
    run.lease_expires_at = None
    run.agent_run_id = agent_run_id
    run.conversation_id = conversation_id
    run.delivery_summary = delivery_summary
    task = await session.get(WorkspaceScheduledTask, run.task_id)
    if task is not None:
        task.last_status = status
        task.last_error = error
        task.last_task_run_id = run.id
        task.last_agent_run_id = agent_run_id
        if conversation_id is not None and task.conversation_policy == "reuse":
            task.conversation_id = conversation_id
    await session.flush()
    return True


async def retry_or_fail_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    worker_id: str,
    now: datetime,
    retry_at: datetime,
    error_message: str,
) -> str | None:
    run = await get_owned_running_run(session, run_id, worker_id=worker_id)
    if run is None:
        return None
    retryable = run.attempt_count < run.max_attempts
    run.worker_id = ""
    run.lease_expires_at = None
    run.error = error_message
    if retryable:
        run.status = "queued"
        run.available_at = retry_at
        run.finished_at = None
    else:
        run.status = "failed"
        run.finished_at = now
        task = await session.get(WorkspaceScheduledTask, run.task_id)
        if task is not None:
            task.last_status = "failed"
            task.last_error = error_message
            task.last_task_run_id = run.id
            task.last_agent_run_id = run.agent_run_id
    await session.flush()
    return run.status


async def recover_expired_leases(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> int:
    result = await session.execute(
        select(WorkspaceScheduledTaskRun)
        .where(
            WorkspaceScheduledTaskRun.status == "running",
            WorkspaceScheduledTaskRun.lease_expires_at <= now,
        )
        .order_by(WorkspaceScheduledTaskRun.lease_expires_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    recovered = 0
    for run in result.scalars().all():
        retryable = run.attempt_count < run.max_attempts
        run.status = "queued" if retryable else "failed"
        run.available_at = now
        run.finished_at = None if retryable else now
        run.worker_id = ""
        run.lease_expires_at = None
        run.error = "The scheduled task worker stopped renewing its lease"
        if not retryable:
            task = await session.get(WorkspaceScheduledTask, run.task_id)
            if task is not None:
                task.last_status = "failed"
                task.last_error = run.error
                task.last_task_run_id = run.id
        recovered += 1
    return recovered


async def add_delivery(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    task_run_id: uuid.UUID,
    route_type: str,
    status: str,
    connection_id: uuid.UUID | None = None,
    provider: str = "",
    external_thread_id: str = "",
    display_name: str = "",
    payload: dict | None = None,
    error: str = "",
    delivered_at: datetime | None = None,
) -> WorkspaceScheduledTaskDelivery:
    delivery = WorkspaceScheduledTaskDelivery(
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
        task_run_id=task_run_id,
        connection_id=connection_id,
        route_type=route_type,
        provider=provider,
        external_thread_id=external_thread_id,
        display_name=display_name,
        status=status,
        payload=payload or {},
        error=error,
        delivered_at=delivered_at,
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def add_notification(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    task_run_id: uuid.UUID,
    event_type: str,
    route_type: str,
    status: str,
    title: str,
    message: str,
    connection_id: uuid.UUID | None = None,
    provider: str = "",
    external_thread_id: str = "",
    display_name: str = "",
    payload: dict | None = None,
    error: str = "",
    delivered_at: datetime | None = None,
) -> WorkspaceScheduledTaskNotification:
    notification = WorkspaceScheduledTaskNotification(
        organization_id=organization_id,
        workspace_id=workspace_id,
        task_id=task_id,
        task_run_id=task_run_id,
        connection_id=connection_id,
        event_type=event_type,
        route_type=route_type,
        provider=provider,
        external_thread_id=external_thread_id,
        display_name=display_name,
        status=status,
        title=title,
        message=message,
        payload=payload or {},
        error=error,
        delivered_at=delivered_at,
    )
    session.add(notification)
    await session.flush()
    return notification
