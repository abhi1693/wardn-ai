from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.agents.models import AgentRun, WorkspaceConversation
from app.modules.chat_providers.models import ChatProviderConnection
from app.modules.scheduled_tasks import repository, service
from app.modules.scheduled_tasks.exceptions import ScheduledTaskNotFoundError
from app.modules.scheduled_tasks.models import (
    WorkspaceScheduledTask,
    WorkspaceScheduledTaskDelivery,
    WorkspaceScheduledTaskRun,
    WorkspaceScheduledTaskSchedule,
)
from app.modules.scheduled_tasks.schemas import (
    WorkspaceScheduledTaskCreate,
    WorkspaceScheduledTaskOutputRoute,
    WorkspaceScheduledTaskRouteTestRequest,
    WorkspaceScheduledTaskScheduleCreate,
)
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.flushed = False
        self.commits = 0
        self.added: list[object] = []
        self.refreshes: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        self.refreshes.append(obj)


class FakeExecutionSession(FakeSession):
    def __init__(self, agent_run: AgentRun) -> None:
        super().__init__()
        self.agent_run = agent_run
        self.refreshed = False

    async def get(self, model, item_id):
        if model is AgentRun and item_id == self.agent_run.id:
            return self.agent_run
        return None

    async def refresh(self, obj) -> None:
        self.refreshed = True


def make_task() -> WorkspaceScheduledTask:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    return WorkspaceScheduledTask(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        created_by_id=uuid4(),
        name="Daily digest",
        instructions="Summarize workspace activity.",
        schedule_type="daily",
        schedule_config={"time": "09:30"},
        timezone="UTC",
        output_routes=[{"route_type": "chat"}],
        notification_rules=service.normalize_notification_rules(None),
        notification_routes=[{"route_type": "chat"}],
        approval_routes=[{"route_type": "chat"}],
        monitoring_config=service.normalize_monitoring_config(None),
        monitoring_status="off",
        notification_state={},
        conversation_policy="reuse",
        is_active=True,
        next_run_at=now,
        last_status="",
        last_error="",
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )


def make_run(task: WorkspaceScheduledTask) -> WorkspaceScheduledTaskRun:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    return WorkspaceScheduledTaskRun(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        agent_id=task.agent_id,
        requested_by_id=task.created_by_id,
        trigger_source="scheduled",
        status="running",
        scheduled_for=now,
        available_at=now,
        attempt_count=1,
        max_attempts=3,
        worker_id="worker-1",
        error="",
        delivery_summary={},
        created_at=now,
        updated_at=now,
    )


def make_delivery(
    task: WorkspaceScheduledTask,
    run: WorkspaceScheduledTaskRun,
    *,
    connection_id=None,
    status: str = "failed",
    text: str = "Final answer",
) -> WorkspaceScheduledTaskDelivery:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    return WorkspaceScheduledTaskDelivery(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        task_run_id=run.id,
        connection_id=connection_id,
        route_type="chat_provider",
        provider="telegram",
        external_thread_id="thread-1",
        display_name="Ops",
        status=status,
        payload=service.delivery_payload_with_text(text=text),
        error="temporary failure" if status == "failed" else "",
        created_at=now,
        updated_at=now,
    )


def make_connection(task: WorkspaceScheduledTask) -> ChatProviderConnection:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    return ChatProviderConnection(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        created_by_id=task.created_by_id,
        provider="telegram",
        name="Telegram",
        external_id="bot",
        display_name="Telegram",
        config={},
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_next_run_supports_interval_daily_and_weekly() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)

    assert service.next_run_at(
        schedule_type="interval",
        schedule_config={"everyMinutes": 15},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 4, 8, 15, tzinfo=UTC)
    assert service.next_run_at(
        schedule_type="daily",
        schedule_config={"time": "07:30"},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 5, 7, 30, tzinfo=UTC)
    assert service.next_run_at(
        schedule_type="weekly",
        schedule_config={"weekday": 1, "time": "09:00"},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def test_next_run_supports_rich_schedule_patterns() -> None:
    now = datetime(2026, 8, 4, 8, 5, tzinfo=UTC)

    assert service.next_run_at(
        schedule_type="daily",
        schedule_config={"times": ["07:30", "10:15"]},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 4, 10, 15, tzinfo=UTC)
    assert service.next_run_at(
        schedule_type="weekdays",
        schedule_config={"times": ["07:00"]},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 5, 7, 0, tzinfo=UTC)
    assert service.next_run_at(
        schedule_type="weekly",
        schedule_config={"weekdays": [0, 2], "times": ["09:00", "17:00"]},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    assert service.next_run_at(
        schedule_type="monthly",
        schedule_config={"monthDays": [4, 15], "times": ["07:00", "12:00"]},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    assert service.next_run_at(
        schedule_type="cron",
        schedule_config={"expression": "*/20 8 * * 1-5"},
        timezone="UTC",
        after=now,
    ) == datetime(2026, 8, 4, 8, 20, tzinfo=UTC)


def test_start_and_end_dates_bound_schedule_runs() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    starts_at = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    ends_at = datetime(2026, 8, 4, 9, 10, tzinfo=UTC)

    assert service.next_run_at(
        schedule_type="interval",
        schedule_config={"everyMinutes": 15},
        timezone="UTC",
        after=now,
        starts_at=starts_at,
        ends_at=ends_at,
    ) == starts_at
    assert service.next_run_at(
        schedule_type="interval",
        schedule_config={"everyMinutes": 15},
        timezone="UTC",
        after=starts_at,
        starts_at=starts_at,
        ends_at=ends_at,
    ) is None


def test_next_runs_preview_merges_multiple_owned_schedules() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    preview = service.next_runs_preview(
        [
            service.ScheduleSpec(
                schedule_type="daily",
                schedule_config={"times": ["09:00", "17:00"]},
                timezone="UTC",
            ),
            service.ScheduleSpec(
                schedule_type="cron",
                schedule_config={"expression": "30 8 * * 1-5"},
                timezone="UTC",
            ),
        ],
        after=now,
        limit=5,
    )

    assert preview == [
        datetime(2026, 8, 4, 8, 30, tzinfo=UTC),
        datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        datetime(2026, 8, 4, 17, 0, tzinfo=UTC),
        datetime(2026, 8, 5, 8, 30, tzinfo=UTC),
        datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    ]


def test_task_response_includes_schedule_rows_and_preview() -> None:
    task = make_task()
    schedule = WorkspaceScheduledTaskSchedule(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        name="Morning and afternoon",
        schedule_type="daily",
        schedule_config={"times": ["09:00", "17:00"]},
        timezone="UTC",
        is_active=True,
        sort_order=0,
        next_run_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
    )

    response = service.task_response(task, schedules=[schedule])

    assert response.schedules[0].id == schedule.id
    assert response.schedules[0].schedule_config == {"times": ["09:00", "17:00"]}
    assert len(response.next_run_preview) == 5


@pytest.mark.asyncio
async def test_get_task_run_returns_deliveries_and_notifications(monkeypatch) -> None:
    task = make_task()
    run = make_run(task)
    delivery = make_delivery(task, run)
    user = User(id=task.created_by_id, email="owner@example.com", is_active=True)
    captured = SimpleNamespace(member_checked=False, run_id=None)

    async def require_member(*args, **kwargs):
        captured.member_checked = True

    async def get_run(*args, **kwargs):
        captured.run_id = kwargs["run_id"]
        return run

    async def list_run_deliveries(*args, **kwargs):
        return {run.id: [delivery]}

    async def list_run_notifications(*args, **kwargs):
        return {}

    monkeypatch.setattr(service, "require_workspace_member", require_member)
    monkeypatch.setattr(service.repository, "get_run", get_run)
    monkeypatch.setattr(service.repository, "list_run_deliveries", list_run_deliveries)
    monkeypatch.setattr(service.repository, "list_run_notifications", list_run_notifications)

    response = await service.get_workspace_scheduled_task_run(
        FakeSession(),
        user,
        task.organization_id,
        task.workspace_id,
        run.id,
    )

    assert captured.member_checked is True
    assert captured.run_id == run.id
    assert response.id == run.id
    assert response.status == "running"
    assert response.deliveries[0].id == delivery.id


@pytest.mark.asyncio
async def test_get_task_run_raises_when_missing(monkeypatch) -> None:
    task = make_task()
    user = User(id=task.created_by_id, email="owner@example.com", is_active=True)

    async def require_member(*args, **kwargs):
        return None

    async def get_run(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "require_workspace_member", require_member)
    monkeypatch.setattr(service.repository, "get_run", get_run)

    with pytest.raises(ScheduledTaskNotFoundError):
        await service.get_workspace_scheduled_task_run(
            FakeSession(),
            user,
            task.organization_id,
            task.workspace_id,
            uuid4(),
        )


@pytest.mark.asyncio
async def test_create_task_refreshes_and_reloads_schedules_before_response(
    monkeypatch,
) -> None:
    task = make_task()
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)

    def schedule_row(name: str) -> WorkspaceScheduledTaskSchedule:
        return WorkspaceScheduledTaskSchedule(
            id=uuid4(),
            organization_id=task.organization_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            name=name,
            schedule_type="daily",
            schedule_config={"times": ["09:00"]},
            timezone=task.timezone,
            is_active=True,
            sort_order=0,
            next_run_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )

    stale_schedule = schedule_row("Stale in-memory schedule")
    reloaded_schedule = schedule_row("Reloaded schedule")
    call_order: list[str] = []
    session = FakeSession()

    async def refresh(obj) -> None:
        call_order.append("refresh")
        session.refreshes.append(obj)

    session.refresh = refresh

    async def require_admin(*args, **kwargs) -> None:
        call_order.append("admin")

    async def ensure_agent(*args, **kwargs):
        return SimpleNamespace(id=task.agent_id)

    async def validate_routes(*args, **kwargs) -> None:
        return None

    async def create_task(*args, **kwargs) -> WorkspaceScheduledTask:
        call_order.append("create")
        return task

    async def sync_schedules(*args, **kwargs) -> list[WorkspaceScheduledTaskSchedule]:
        call_order.append("sync")
        return [stale_schedule]

    async def list_schedules(*args, **kwargs) -> list[WorkspaceScheduledTaskSchedule]:
        call_order.append("list")
        return [reloaded_schedule]

    monkeypatch.setattr(service, "require_workspace_admin", require_admin)
    monkeypatch.setattr(service.agent_service, "ensure_workspace_assistant_agent", ensure_agent)
    monkeypatch.setattr(service, "validate_output_routes", validate_routes)
    monkeypatch.setattr(service.repository, "create_task", create_task)
    monkeypatch.setattr(service, "sync_task_schedules", sync_schedules)
    monkeypatch.setattr(service.repository, "list_task_schedules", list_schedules)

    response = await service.create_workspace_scheduled_task(
        session,
        User(id=task.created_by_id, email="owner@example.com", is_active=True),
        task.organization_id,
        task.workspace_id,
        WorkspaceScheduledTaskCreate(
            name=task.name,
            instructions=task.instructions,
            timezone=task.timezone,
            schedules=[
                WorkspaceScheduledTaskScheduleCreate(
                    name="Daily",
                    schedule_type="daily",
                    schedule_config={"times": ["09:00"]},
                    timezone=task.timezone,
                ),
            ],
            output_routes=[WorkspaceScheduledTaskOutputRoute(route_type="chat")],
        ),
    )

    assert session.refreshes == [task]
    assert call_order.index("refresh") < call_order.index("list")
    assert response.schedules[0].name == "Reloaded schedule"


def test_timezone_aliases_are_normalized_for_browser_values() -> None:
    assert service.normalize_timezone(" Asia/Calcutta ") == "Asia/Kolkata"
    assert service.zoneinfo_for("Asia/Calcutta").key == "Asia/Kolkata"
    assert service.next_run_at(
        schedule_type="daily",
        schedule_config={"time": "09:00"},
        timezone="Asia/Calcutta",
        after=datetime(2026, 8, 4, 2, 0, tzinfo=UTC),
    ) == datetime(2026, 8, 4, 3, 30, tzinfo=UTC)


def test_scheduled_task_run_status_splits_delivery_outcomes() -> None:
    assert (
        service.scheduled_task_run_status(
            "succeeded",
            {"total": 2, "sent": 2, "failed": 0},
        )
        == "succeeded"
    )
    assert (
        service.scheduled_task_run_status(
            "succeeded",
            {"total": 2, "sent": 1, "failed": 1},
        )
        == "partially_delivered"
    )
    assert (
        service.scheduled_task_run_status(
            "succeeded",
            {"total": 1, "sent": 0, "failed": 1},
        )
        == "delivery_failed"
    )
    assert service.scheduled_task_run_status("failed", {"sent": 1, "failed": 0}) == "failed"
    assert (
        service.scheduled_task_run_status("waiting_confirmation", {"sent": 0, "failed": 1})
        == "waiting_confirmation"
    )


def test_due_and_claim_statements_use_skip_locked() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)

    due_statement = repository.due_task_statement(now).compile(
        dialect=postgresql.dialect()
    )
    due_sql = str(due_statement).upper()
    claim_statement = repository.claimable_run_statement(now).compile(
        dialect=postgresql.dialect()
    )
    claim_sql = str(claim_statement).upper()

    assert "FOR UPDATE SKIP LOCKED" in due_sql
    assert "NEXT_RUN_AT" in due_sql
    assert "NOT (EXISTS" in due_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "AVAILABLE_AT" in claim_sql
    assert "NOT (EXISTS" in claim_sql
    assert due_statement.params["status_1"] == [
        "queued",
        "running",
        "waiting_confirmation",
    ]
    assert claim_statement.params["status_2"] == [
        "queued",
        "running",
        "waiting_confirmation",
    ]


def test_output_routes_default_to_builtin_chat() -> None:
    assert service.normalize_output_routes([]) == [
        {
            "route_type": "chat",
            "connection_id": None,
            "external_thread_id": "",
            "display_name": "",
        }
    ]


def test_notification_rules_default_to_failure_approval_and_delivery_failure() -> None:
    assert service.normalize_notification_rules(None) == {
        "on_failure": True,
        "on_waiting_approval": True,
        "on_no_output": False,
        "on_delivery_failure": True,
        "on_meaningful_update": False,
    }


def test_monitoring_config_defaults_to_off_with_change_delivery() -> None:
    assert service.normalize_monitoring_config(None) == {
        "enabled": False,
        "notify_on_change": True,
        "deliver_on_change_only": True,
        "baseline_on_first_run": True,
        "stop_conditions": {
            "after_first_change": False,
            "after_change_count": None,
            "after_run_count": None,
            "after_unchanged_count": None,
        },
    }


def test_monitoring_records_baseline_and_suppresses_unchanged_delivery() -> None:
    task = make_task()
    task.monitoring_config = service.normalize_monitoring_config({"enabled": True})
    run = make_run(task)

    baseline = service.evaluate_monitoring_result(
        task=task,
        run=run,
        reply=service.TaskRunReply(text="Open issues: 3", kind="assistant"),
    )

    assert baseline.deliver_output is False
    assert baseline.summary["monitoring"]["status"] == "baseline"
    assert task.monitoring_status == "baseline"
    assert service.monitoring_state_value(task)["lastOutputHash"] == service.output_text_hash(
        "Open issues: 3"
    )

    unchanged = service.evaluate_monitoring_result(
        task=task,
        run=make_run(task),
        reply=service.TaskRunReply(text="open   issues: 3", kind="assistant"),
    )

    assert unchanged.deliver_output is False
    assert unchanged.summary["monitoring"]["status"] == "unchanged"
    assert unchanged.summary["monitoring"]["changed"] is False
    assert unchanged.summary["monitoring"]["consecutiveUnchangedCount"] == 1


def test_monitoring_detects_change_and_stop_condition_pauses_task() -> None:
    task = make_task()
    task.monitoring_config = service.normalize_monitoring_config(
        {"enabled": True, "stopConditions": {"afterFirstChange": True}}
    )
    service.evaluate_monitoring_result(
        task=task,
        run=make_run(task),
        reply=service.TaskRunReply(text="Version: 1.0.0", kind="assistant"),
    )

    changed = service.evaluate_monitoring_result(
        task=task,
        run=make_run(task),
        reply=service.TaskRunReply(text="Version: 1.0.1", kind="assistant"),
    )

    assert changed.deliver_output is True
    assert changed.summary["monitoring"]["changed"] is True
    assert changed.summary["monitoring"]["status"] == "stopped"
    assert changed.summary["monitoring"]["stopReason"] == "after_first_change"
    assert task.is_active is False
    assert task.next_run_at is None
    assert task.monitoring_status == "stopped"
    assert service.notification_events_for_run(
        task=task,
        status="succeeded",
        delivery_summary={"failed": 0, **changed.summary},
    ) == ["meaningful_update"]
    assert "Previous:" in service.notification_message(
        event_type="meaningful_update",
        task=task,
        run=make_run(task),
        error="",
        delivery_summary=changed.summary,
    )


def test_notification_events_include_enabled_run_conditions() -> None:
    task = make_task()
    task.notification_rules = service.normalize_notification_rules(
        {
            "onFailure": True,
            "onWaitingApproval": True,
            "onNoOutput": True,
            "onDeliveryFailure": True,
            "onMeaningfulUpdate": True,
        }
    )

    events = service.notification_events_for_run(
        task=task,
        status="partially_delivered",
        delivery_summary={
            "failed": 1,
            "outputKind": "assistant",
            "outputHash": service.output_text_hash("New result"),
            "outputPreview": "New result",
        },
    )

    assert events == ["delivery_failure", "meaningful_update"]
    assert task.notification_state["lastMeaningfulOutputHash"] == service.output_text_hash(
        "New result"
    )

    assert (
        service.notification_events_for_run(
            task=task,
            status="succeeded",
            delivery_summary={
                "failed": 0,
                "outputKind": "assistant",
                "outputHash": service.output_text_hash("New result"),
                "outputPreview": "New result",
            },
        )
        == []
    )


def test_notification_events_include_no_output_when_enabled() -> None:
    task = make_task()
    task.notification_rules = service.normalize_notification_rules(
        {
            "onNoOutput": True,
        }
    )

    assert service.notification_events_for_run(
        task=task,
        status="succeeded",
        delivery_summary={"failed": 0, "outputKind": "empty"},
    ) == ["no_output"]


def test_output_route_requires_provider_conversation() -> None:
    with pytest.raises(ValueError, match="conversation"):
        WorkspaceScheduledTaskOutputRoute(
            route_type="chat_provider",
            connection_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_route_test_sends_provider_message_without_task(monkeypatch) -> None:
    task = make_task()
    user = User(id=task.created_by_id, email="owner@example.com", is_active=True)
    connection = make_connection(task)
    route = WorkspaceScheduledTaskOutputRoute(
        route_type="chat_provider",
        connection_id=connection.id,
        external_thread_id="thread-1",
        display_name="Ops",
    )
    captured = {}

    async def require_admin(*args, **kwargs):
        captured["admin_checked"] = True

    async def get_connection(*args, **kwargs):
        return connection

    async def send_provider_text_message(*args, **kwargs):
        captured["text"] = kwargs["text"]
        captured["thread"] = kwargs["external_thread_id"]
        return {"message_id": "test-1"}

    monkeypatch.setattr(service, "require_workspace_admin", require_admin)
    monkeypatch.setattr(service.chat_provider_repository, "get_connection", get_connection)
    monkeypatch.setattr(
        service.chat_provider_service,
        "send_provider_text_message",
        send_provider_text_message,
    )
    monkeypatch.setattr(
        service.chat_provider_service,
        "provider_response_message_id",
        lambda *_args, **_kwargs: "test-1",
    )

    session = FakeSession()
    response = await service.test_workspace_scheduled_task_route(
        session,
        user,
        task.organization_id,
        task.workspace_id,
        WorkspaceScheduledTaskRouteTestRequest(
            route=route,
            message="Test scheduled route",
        ),
    )

    assert captured["admin_checked"] is True
    assert captured["text"] == "Test scheduled route"
    assert captured["thread"] == "thread-1"
    assert response.status == "sent"
    assert response.payload == {"telegram": {"message_id": "test-1"}}
    assert len(session.added) == 1
    assert session.added[0].event_type == "scheduled_task.route_test"


@pytest.mark.asyncio
async def test_retry_delivery_resends_saved_text_and_updates_run(monkeypatch) -> None:
    task = make_task()
    run = make_run(task)
    run.status = "delivery_failed"
    run.delivery_summary = {
        "total": 1,
        "sent": 0,
        "failed": 1,
        "outputKind": "assistant",
        "outputPreview": "Final answer",
    }
    task.last_task_run_id = run.id
    task.last_status = "delivery_failed"
    user = User(id=task.created_by_id, email="owner@example.com", is_active=True)
    connection = make_connection(task)
    delivery = make_delivery(task, run, connection_id=connection.id, text="Final answer")
    captured = {}

    async def require_admin(*args, **kwargs):
        captured["admin_checked"] = True

    async def get_task(*args, **kwargs):
        return task

    async def get_task_run(*args, **kwargs):
        captured["run_for_update"] = kwargs["for_update"]
        return run

    async def get_delivery(*args, **kwargs):
        captured["delivery_for_update"] = kwargs["for_update"]
        return delivery

    async def list_run_deliveries(*args, **kwargs):
        return {run.id: [delivery]}

    async def list_run_notifications(*args, **kwargs):
        return {}

    async def get_connection(*args, **kwargs):
        return connection

    async def send_provider_text_message(*args, **kwargs):
        captured["text"] = kwargs["text"]
        captured["thread"] = kwargs["external_thread_id"]
        return {"message_id": "retry-1"}

    monkeypatch.setattr(service, "require_workspace_admin", require_admin)
    monkeypatch.setattr(service.repository, "get_task", get_task)
    monkeypatch.setattr(service.repository, "get_task_run", get_task_run)
    monkeypatch.setattr(service.repository, "get_delivery", get_delivery)
    monkeypatch.setattr(service.repository, "list_run_deliveries", list_run_deliveries)
    monkeypatch.setattr(service.repository, "list_run_notifications", list_run_notifications)
    monkeypatch.setattr(service.chat_provider_repository, "get_connection", get_connection)
    monkeypatch.setattr(
        service.chat_provider_service,
        "send_provider_text_message",
        send_provider_text_message,
    )
    monkeypatch.setattr(
        service.chat_provider_service,
        "provider_response_message_id",
        lambda *_args, **_kwargs: "retry-1",
    )

    response = await service.retry_workspace_scheduled_task_delivery(
        FakeSession(),
        user,
        task.organization_id,
        task.workspace_id,
        task.id,
        run.id,
        delivery.id,
    )

    assert captured["admin_checked"] is True
    assert captured["run_for_update"] is True
    assert captured["delivery_for_update"] is True
    assert captured["text"] == "Final answer"
    assert captured["thread"] == "thread-1"
    assert delivery.status == "sent"
    assert delivery.error == ""
    assert delivery.payload["retryCount"] == 1
    assert run.status == "succeeded"
    assert run.delivery_summary["sent"] == 1
    assert run.delivery_summary["failed"] == 0
    assert task.last_status == "succeeded"
    assert response.status == "succeeded"
    assert response.deliveries[0].can_retry is False
    assert response.deliveries[0].retry_count == 1


@pytest.mark.asyncio
async def test_prepare_agent_run_uses_scheduled_trigger(monkeypatch) -> None:
    task = make_task()
    run = make_run(task)
    actor = User(id=task.created_by_id, email="owner@example.com", is_active=True)
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        agent_id=task.agent_id,
        created_by_id=actor.id,
        title="Scheduled: Daily digest",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        agent_id=task.agent_id,
        conversation_id=conversation.id,
        triggered_by_id=actor.id,
        trigger_type=service.SCHEDULED_AGENT_TRIGGER,
        status="running",
        started_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
        error="",
    )
    captured = SimpleNamespace(trigger_type="", payload=None, session_factory=None)

    async def ensure_task_conversation(*args, **kwargs):
        return conversation

    async def latest_scheduled_agent_run(*args, **kwargs):
        return agent_run

    async def stream_agent_chat(*args, **kwargs):
        captured.payload = args[4]
        captured.trigger_type = kwargs["trigger_type"]
        captured.session_factory = kwargs["session_factory"]

        async def stream():
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return stream()

    session_factory = object()
    monkeypatch.setattr(service, "ensure_task_conversation", ensure_task_conversation)
    monkeypatch.setattr(service, "latest_scheduled_agent_run", latest_scheduled_agent_run)
    monkeypatch.setattr(service.agent_service, "stream_agent_chat", stream_agent_chat)

    conversation_id, agent_run_id, stream = await service.prepare_agent_run_for_task(
        FakeSession(),
        task=task,
        run=run,
        actor=actor,
        session_factory=session_factory,
    )

    assert conversation_id == conversation.id
    assert agent_run_id == agent_run.id
    assert run.agent_run_id == agent_run.id
    assert captured.trigger_type == service.SCHEDULED_AGENT_TRIGGER
    assert captured.session_factory is session_factory
    assert captured.payload.id == str(conversation.id)
    assert "Scheduled task: Daily digest" in captured.payload.messages[0].parts[0]["text"]
    async for _chunk in stream:
        pass


@pytest.mark.asyncio
async def test_execute_claimed_task_run_records_partial_delivery(monkeypatch) -> None:
    task = make_task()
    run = make_run(task)
    actor = User(id=task.created_by_id, email="owner@example.com", is_active=True)
    conversation_id = uuid4()
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        agent_id=task.agent_id,
        conversation_id=conversation_id,
        triggered_by_id=actor.id,
        trigger_type=service.SCHEDULED_AGENT_TRIGGER,
        status="succeeded",
        started_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
        error="",
    )
    captured = {}

    async def get_task(*args, **kwargs):
        return task

    async def resolve_task_actor(*args, **kwargs):
        return actor

    async def prepare_agent_run_for_task(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"finish","finishReason":"stop"}\n\n'

        return conversation_id, agent_run.id, stream()

    async def deliver_task_run_output(*args, **kwargs):
        return {"total": 2, "sent": 1, "failed": 1}

    async def complete_run(session, run_id, **kwargs):
        captured["run_id"] = run_id
        captured["status"] = kwargs["status"]
        captured["delivery_summary"] = kwargs["delivery_summary"]
        return True

    async def dispatch_task_run_notifications(*args, **kwargs):
        captured["notification_status"] = kwargs["status"]

    monkeypatch.setattr(service.repository, "get_task", get_task)
    monkeypatch.setattr(service, "resolve_task_actor", resolve_task_actor)
    monkeypatch.setattr(service, "prepare_agent_run_for_task", prepare_agent_run_for_task)
    monkeypatch.setattr(service, "deliver_task_run_output", deliver_task_run_output)
    monkeypatch.setattr(service.repository, "complete_run", complete_run)
    monkeypatch.setattr(
        service,
        "dispatch_task_run_notifications",
        dispatch_task_run_notifications,
    )

    session = FakeExecutionSession(agent_run)
    await service.execute_claimed_task_run(
        session,
        run=run,
        worker_id="worker-1",
        session_factory=object(),
    )

    assert session.commits == 1
    assert session.refreshed is True
    assert captured["run_id"] == run.id
    assert captured["status"] == "partially_delivered"
    assert captured["notification_status"] == "partially_delivered"
    assert captured["delivery_summary"] == {"total": 2, "sent": 1, "failed": 1}


@pytest.mark.asyncio
async def test_execute_claimed_task_run_routes_waiting_approval_notifications(
    monkeypatch,
) -> None:
    task = make_task()
    run = make_run(task)
    actor = User(id=task.created_by_id, email="owner@example.com", is_active=True)
    conversation_id = uuid4()
    approval_id = uuid4()
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=task.organization_id,
        workspace_id=task.workspace_id,
        agent_id=task.agent_id,
        conversation_id=conversation_id,
        triggered_by_id=actor.id,
        trigger_type=service.SCHEDULED_AGENT_TRIGGER,
        status="waiting_confirmation",
        started_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
        error="",
    )
    captured = {"notifications": []}

    async def get_task(*args, **kwargs):
        return task

    async def resolve_task_actor(*args, **kwargs):
        return actor

    async def prepare_agent_run_for_task(*args, **kwargs):
        async def stream():
            yield 'data: {"type":"tool-result","status":"requires_confirmation"}\n\n'

        return conversation_id, agent_run.id, stream()

    async def reply_for_task_run(*args, **kwargs):
        return service.TaskRunReply(
            text="Open approval: https://ai.home/approval",
            kind="approval",
            approval_id=approval_id,
        )

    async def complete_run(session, run_id, **kwargs):
        run.status = kwargs["status"]
        run.agent_run_id = kwargs["agent_run_id"]
        run.conversation_id = kwargs["conversation_id"]
        captured["status"] = kwargs["status"]
        captured["delivery_summary"] = kwargs["delivery_summary"]
        return True

    async def dispatch_task_run_notifications(*args, **kwargs):
        captured["notifications"].append(kwargs["status"])
        if kwargs["status"] == "waiting_confirmation":
            captured["notification_summary"] = kwargs["delivery_summary"]

    async def deliver_task_run_output(*args, **kwargs):
        captured["delivered_after_approval"] = True
        return {
            "total": 1,
            "sent": 1,
            "failed": 0,
            "outputKind": "assistant",
            "hasOutput": True,
            "outputHash": "hash",
            "outputPreview": "Approved result",
        }

    async def wait_for_task_run_approval(*args, **kwargs):
        captured["waited_for_approval"] = kwargs["approval_id"]
        agent_run.status = "succeeded"
        return "succeeded", ""

    monkeypatch.setattr(service.repository, "get_task", get_task)
    monkeypatch.setattr(service, "resolve_task_actor", resolve_task_actor)
    monkeypatch.setattr(service, "prepare_agent_run_for_task", prepare_agent_run_for_task)
    monkeypatch.setattr(service, "reply_for_task_run", reply_for_task_run)
    monkeypatch.setattr(service.repository, "complete_run", complete_run)
    monkeypatch.setattr(
        service,
        "dispatch_task_run_notifications",
        dispatch_task_run_notifications,
    )
    monkeypatch.setattr(service, "deliver_task_run_output", deliver_task_run_output)
    monkeypatch.setattr(service, "wait_for_task_run_approval", wait_for_task_run_approval)

    session = FakeExecutionSession(agent_run)
    await service.execute_claimed_task_run(
        session,
        run=run,
        worker_id="worker-1",
        session_factory=object(),
    )

    assert session.commits == 2
    assert captured["waited_for_approval"] == approval_id
    assert captured["delivered_after_approval"] is True
    assert captured["status"] == "succeeded"
    assert captured["notification_summary"] == {
        "total": 0,
        "sent": 0,
        "failed": 0,
        "outputKind": "approval",
        "hasOutput": False,
        "outputHash": "",
        "outputPreview": "Open approval: https://ai.home/approval",
        "approvalId": str(approval_id),
    }
    assert captured["delivery_summary"] == {
        "total": 1,
        "sent": 1,
        "failed": 0,
        "outputKind": "assistant",
        "hasOutput": True,
        "outputHash": "hash",
        "outputPreview": "Approved result",
    }
    assert captured["notifications"] == ["waiting_confirmation", "succeeded"]
