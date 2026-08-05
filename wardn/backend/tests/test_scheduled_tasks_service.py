from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.agents.models import AgentRun, WorkspaceConversation
from app.modules.scheduled_tasks import repository, service
from app.modules.scheduled_tasks.models import (
    WorkspaceScheduledTask,
    WorkspaceScheduledTaskRun,
    WorkspaceScheduledTaskSchedule,
)
from app.modules.scheduled_tasks.schemas import WorkspaceScheduledTaskOutputRoute
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.flushed = False
        self.commits = 0

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.commits += 1


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


def test_timezone_aliases_are_normalized_for_browser_values() -> None:
    assert service.normalize_timezone(" Asia/Calcutta ") == "Asia/Kolkata"
    assert service.zoneinfo_for("Asia/Calcutta").key == "Asia/Kolkata"
    assert service.next_run_at(
        schedule_type="daily",
        schedule_config={"time": "09:00"},
        timezone="Asia/Calcutta",
        after=datetime(2026, 8, 4, 2, 0, tzinfo=UTC),
    ) == datetime(2026, 8, 4, 3, 30, tzinfo=UTC)


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


def test_output_route_requires_provider_conversation() -> None:
    with pytest.raises(ValueError, match="conversation"):
        WorkspaceScheduledTaskOutputRoute(
            route_type="chat_provider",
            connection_id=uuid4(),
        )


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
