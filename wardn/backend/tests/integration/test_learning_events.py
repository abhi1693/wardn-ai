import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.agents import chat_orchestrator, tool_execution
from app.modules.agents import repository as agents
from app.modules.agents.chat_orchestrator import persisted_agent_chat_stream
from app.modules.agents.models import Agent, AgentRun, WorkspaceConversation
from app.modules.agents.types import (
    AgentChatReasoningSummaryEvent,
    AgentChatTextEvent,
    AgentRuntimeTool,
    AgentToolCall,
)
from app.modules.learning import capture, repository
from app.modules.learning.models import LearningEvent, LearningWorkerCursor
from app.modules.learning.schemas import EventCreate, EventType
from app.modules.learning.service import emitter
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_runtime import service as runtime
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.organizations.models import Organization, Workspace
from app.modules.scheduled_tasks import repository as schedules
from app.modules.scheduled_tasks.models import WorkspaceScheduledTask

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def cleanup_learning_fixtures(postgres_engine):
    yield
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with factory.begin() as session:
        await session.execute(delete(Organization).where(Organization.slug.like("learning-test-%")))


async def seed(factory, *, conversation=True):
    async with factory.begin() as session:
        org = Organization(
            name="Learning test", slug=f"learning-test-{uuid.uuid4().hex}", status="active"
        )
        session.add(org)
        await session.flush()
        ws = Workspace(
            organization_id=org.id,
            name="Learning",
            slug=f"learning-test-{uuid.uuid4().hex}",
            status="active",
        )
        session.add(ws)
        await session.flush()
        agent = Agent(
            organization_id=org.id,
            workspace_id=ws.id,
            name="Learning",
            instructions="Test agent",
            scope="workspace",
        )
        session.add(agent)
        await session.flush()
        chat = (
            WorkspaceConversation(
                organization_id=org.id, workspace_id=ws.id, agent_id=agent.id, title="Test"
            )
            if conversation
            else None
        )
        if chat:
            session.add(chat)
            await session.flush()
        run = await agents.create_agent_run(
            session,
            organization_id=org.id,
            workspace_id=ws.id,
            agent_id=agent.id,
            conversation_id=chat.id if chat else None,
            triggered_by_id=None,
        )
        return SimpleNamespace(org=org, ws=ws, agent=agent, chat=chat, run=run)


def scope(seed):
    return dict(organization_id=seed.org.id, workspace_id=seed.ws.id)


def event(seed, key, **changes):
    values = dict(
        **scope(seed),
        execution_id=seed.run.id,
        execution_kind="agent_run",
        source="user",
        event_type=EventType.USER_FEEDBACK,
        idempotency_key=key,
        occurred_at=datetime.now(UTC),
        data={"feedback": "worked"},
    )
    return EventCreate(**{**values, **changes})


async def events(factory, seed):
    async with factory() as session:
        return await repository.list_events(session, **scope(seed), limit=1000)


@pytest.mark.asyncio
async def test_conversation_events_reconstruct_execution_without_private_payloads(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory.begin() as session:
        message = await agents.append_conversation_message(
            session,
            conversation_id=s.chat.id,
            agent_run_id=s.run.id,
            role="user",
            content="Analyze SEO password=never-copy-me",
            parts=[],
        )

    async def stream():
        yield AgentChatReasoningSummaryEvent(summary="private scratchpad never-copy-me")
        yield AgentChatTextEvent(text="Analysis is ready.")

    chunks = [
        chunk
        async for chunk in persisted_agent_chat_stream(
            s.chat,
            stream(),
            s.run,
            session_factory=factory,
        )
    ]
    rows = await events(factory, s)
    assert [row.event_type for row in rows] == [
        "execution.started",
        "user.message",
        "agent.response",
        "execution.succeeded",
    ]
    assert [row.sequence_number for row in rows] == [1, 2, 3, 4]
    assert all(row.execution_id == s.run.id and row.conversation_id == s.chat.id for row in rows)
    assert rows[1].data["source_ref"] == f"conversation_messages:{message.id}"
    assert "never-copy-me" not in json.dumps([row.data for row in rows])
    assert chunks


@pytest.mark.asyncio
async def test_concurrent_append_is_ordered_and_duplicate_retries_are_idempotent(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)

    async def append(key):
        async with factory.begin() as session:
            return (await emitter.emit(session, event(s, key))).id

    await asyncio.gather(*(append(f"event-{i}") for i in range(15)))
    duplicate_ids = await asyncio.gather(*(append("same-event") for _ in range(8)))
    assert len(set(duplicate_ids)) == 1
    rows = await events(factory, s)
    assert len(rows) == 17
    assert [row.sequence_number for row in rows] == list(range(1, 18))
    assert len({row.workspace_sequence for row in rows}) == 17
    async with factory.begin() as session:
        with pytest.raises(ValueError, match="conflicts"):
            await emitter.emit(
                session, event(s, "same-event", event_type=EventType.USER_CORRECTION)
            )


@pytest.mark.asyncio
async def test_cursor_does_not_skip_uncommitted_events_across_executions(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory.begin() as session:
        other = await agents.create_agent_run(
            session,
            **scope(s),
            agent_id=s.agent.id,
            conversation_id=s.chat.id,
            triggered_by_id=None,
        )
    first = factory()
    await emitter.emit(first, event(s, "slow-first"))
    attempted = asyncio.Event()

    async def second_writer():
        async with factory.begin() as session:
            attempted.set()
            await emitter.emit(session, event(s, "fast-second", execution_id=other.id))

    second = asyncio.create_task(second_writer())
    seen = []

    async def consume(session, batch):
        seen.extend(row.idempotency_key for row in batch)

    try:
        await attempted.wait()
        async with factory.begin() as session:
            assert (
                await repository.consume_batch(
                    session, worker_name="test", **scope(s), consume=consume
                )
                == 2
            )
        assert "slow-first" not in seen
        await first.commit()
        await asyncio.wait_for(second, timeout=5)
        async with factory.begin() as session:
            assert (
                await repository.consume_batch(
                    session, worker_name="test", **scope(s), consume=consume
                )
                == 2
            )
        assert seen[-2:] == ["slow-first", "fast-second"]
    finally:
        await first.rollback()
        await first.close()
        if not second.done():
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_failure_rolls_back_effects_and_cursor_then_replays(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)

    async def failed(session, batch):
        await session.execute(
            update(Workspace).where(Workspace.id == s.ws.id).values(name="changed")
        )
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        async with factory.begin() as session:
            await repository.consume_batch(session, worker_name="test", **scope(s), consume=failed)
    async with factory() as session:
        assert (await session.get(Workspace, s.ws.id)).name == "Learning"
        assert (
            await session.scalar(
                select(LearningWorkerCursor).where(LearningWorkerCursor.workspace_id == s.ws.id)
            )
            is None
        )

    seen = []

    async def success(session, batch):
        seen.extend(row.id for row in batch)

    async def process():
        async with factory.begin() as session:
            return await repository.consume_batch(
                session, worker_name="test", **scope(s), consume=success
            )

    assert sorted(await asyncio.gather(process(), process())) == [0, 1]
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_source_action_and_event_rollback_together(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory() as session:
        run = await agents.create_agent_run(
            session, **scope(s), agent_id=s.agent.id, conversation_id=None, triggered_by_id=None
        )
        run_id = run.id
        await session.rollback()
    async with factory() as session:
        assert await session.get(AgentRun, run_id) is None
        assert await repository.list_events(session, **scope(s), execution_id=run_id) == []


@pytest.mark.asyncio
async def test_wrong_workspace_and_cross_tenant_provenance_are_rejected(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    a, b = await seed(factory), await seed(factory)
    async with factory.begin() as session:
        assert (
            await repository.list_events(session, organization_id=a.org.id, workspace_id=b.ws.id)
            == []
        )
        with pytest.raises(ValueError, match="workspace"):
            await emitter.emit(session, event(a, "wrong-workspace", workspace_id=b.ws.id))
        with pytest.raises(ValueError, match="execution"):
            await emitter.emit(session, event(a, "wrong-run", execution_id=b.run.id))
        with pytest.raises(ValueError, match="conversation_id"):
            await emitter.emit(session, event(a, "wrong-chat", conversation_id=b.chat.id))
        with pytest.raises(ValueError, match="parent"):
            await emitter.emit(
                session, event(a, "wrong-parent", parent_event_id=(await events(factory, b))[0].id)
            )


@pytest.mark.asyncio
async def test_database_prevents_update_delete_and_wrong_tenant_insert(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    row = (await events(factory, s))[0]
    for statement in (
        update(LearningEvent).where(LearningEvent.id == row.id).values(data={"changed": True}),
        delete(LearningEvent).where(LearningEvent.id == row.id),
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with factory.begin() as session:
                await session.execute(statement)
    with pytest.raises(DBAPIError, match="organization mismatch"):
        async with factory.begin() as session:
            await session.execute(
                text("""
                INSERT INTO learning_events SELECT gen_random_uuid(), :org, workspace_id,
                execution_id, execution_kind, agent_id, conversation_id, objective_id,
                scheduled_task_id, scheduled_run_id, parent_event_id, tool_call_id,
                999, 999, event_type, source, 'invalid-scope', trace_id, span_id, data,
                occurred_at, created_at FROM learning_events WHERE id = :id
            """),
                {"org": uuid.uuid4(), "id": row.id},
            )
    # Source cleanup retains provenance; explicit workspace teardown erases learning data.
    async with factory.begin() as session:
        await session.execute(delete(AgentRun).where(AgentRun.id == s.run.id))
    assert len(await events(factory, s)) == 1
    async with factory.begin() as session:
        await session.execute(delete(Workspace).where(Workspace.id == s.ws.id))
    assert await events(factory, s) == []


async def prepare_runtime(session, s, monkeypatch, *, with_agent=True):
    installation = MCPServerInstallation(
        workspace_id=s.ws.id,
        server_name="test/search",
        installed_version="1.0.0",
        status="enabled",
        install_type="metadata",
        install_path="",
        runtime_config={},
        secret_references={},
        install_error="",
        installed_at=datetime.now(UTC),
    )
    session.add(installation)
    await session.flush()
    runtime_session = MCPRuntimeSession(
        organization_id=s.org.id,
        workspace_id=s.ws.id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind="remote",
        status="running",
    )
    session.add(runtime_session)
    await session.flush()

    async def materialize(session, installation):
        return installation

    async def ensure(session, *args, **kwargs):
        return await session.get(MCPRuntimeSession, runtime_session.id)

    monkeypatch.setattr(runtime, "materialize_installation_secret_references", materialize)
    monkeypatch.setattr(runtime, "ensure_runtime_session", ensure)
    return await runtime.prepare_tool_call_tracking(
        session,
        installation,
        MCPServerVersion(name="test/search", version="1.0.0"),
        tool_name="search",
        arguments={"password": "super-secret", "query": "private customer"},
        agent_id=s.agent.id if with_agent else None,
        agent_run_id=s.run.id if with_agent else None,
        manager=object(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "is_error", "exception"])
async def test_mcp_tracking_events_reference_real_invocations(
    postgres_engine, monkeypatch, outcome
):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory.begin() as session:
        prepared = await prepare_runtime(session, s, monkeypatch)
    async with factory.begin() as session:
        kwargs = (
            {"error": RuntimeError("password=super-secret")}
            if outcome == "exception"
            else {
                "result": {
                    "content": [{"type": "text", "text": "private customer super-secret"}],
                    "isError": outcome == "is_error",
                }
            }
        )
        await runtime.finalize_prepared_tool_call(session, prepared, tool_name="search", **kwargs)
        await runtime.finalize_prepared_tool_call(session, prepared, tool_name="search", **kwargs)
        session.info["learning_invocation_id"] = prepared.invocation_id
        await capture.tool_observed(session)
    rows = await events(factory, s)
    assert [row.event_type for row in rows] == [
        "execution.started",
        "tool.selected",
        "tool.call_started",
        "tool.call_completed" if outcome == "success" else "tool.call_failed",
        "tool.result_observed",
    ]
    assert all(row.tool_call_id == prepared.invocation_id for row in rows[1:])
    assert "super-secret" not in json.dumps([row.data for row in rows])
    assert "private customer" not in json.dumps([row.data for row in rows])


@pytest.mark.asyncio
async def test_standalone_gateway_call_has_execution_and_failure_recovery(
    postgres_engine, monkeypatch
):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory.begin() as session:
        prepared = await prepare_runtime(session, s, monkeypatch, with_agent=False)
        prepared.invocation.started_at = datetime.now(UTC) - timedelta(hours=1)
    async with factory.begin() as session:
        await runtime.recover_stale_tool_invocations(session, stale_after_seconds=600)
    rows = [row for row in await events(factory, s) if row.execution_id == prepared.invocation_id]
    assert [row.event_type for row in rows] == [
        "execution.started",
        "tool.selected",
        "tool.call_started",
        "tool.call_failed",
        "execution.failed",
    ]
    assert all(row.execution_kind == "tool_invocation" for row in rows)


@pytest.mark.asyncio
async def test_scheduled_claim_retry_agent_link_and_completion(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        task = WorkspaceScheduledTask(
            **scope(s),
            agent_id=s.agent.id,
            name="SEO",
            instructions="Analyze SEO",
            schedule_type="manual",
        )
        session.add(task)
        await session.flush()
        scheduled = await schedules.create_task_run(
            session,
            task=task,
            scheduled_for=now,
            available_at=now,
            trigger_source="manual",
            requested_by_id=None,
        )
    async with factory.begin() as session:
        claimed = await schedules.claim_next_run(
            session, worker_id="learning-test", now=now, lease_seconds=60
        )
        assert claimed.id == scheduled.id
    async with factory.begin() as session:
        await schedules.retry_or_fail_run(
            session,
            scheduled.id,
            worker_id="learning-test",
            now=now,
            retry_at=now,
            error_message="transient failure",
        )
    async with factory.begin() as session:
        claimed = await schedules.claim_next_run(
            session, worker_id="learning-test", now=now, lease_seconds=60
        )
        run = await agents.create_agent_run(
            session,
            **scope(s),
            agent_id=s.agent.id,
            conversation_id=s.chat.id,
            triggered_by_id=None,
            trigger_type="scheduled_task",
            scheduled_run_id=scheduled.id,
        )
        claimed.agent_run_id = run.id
        claimed.conversation_id = s.chat.id
        await session.flush()
        await agents.finish_agent_run(session, run, status="succeeded")
        await schedules.complete_run(
            session,
            scheduled.id,
            worker_id="learning-test",
            now=now,
            status="delivery_failed",
            error="delivery failed",
            agent_run_id=run.id,
            conversation_id=s.chat.id,
            delivery_summary={},
        )
    rows = [row for row in await events(factory, s) if row.scheduled_run_id == scheduled.id]
    assert [row.event_type for row in rows] == [
        "execution.started",
        "execution.paused",
        "execution.resumed",
        "execution.started",
        "execution.succeeded",
        "execution.failed",
    ]
    assert all(row.scheduled_task_id == task.id for row in rows)
    assert rows[3].execution_id == run.id
    assert rows[-1].execution_id == scheduled.id


@pytest.mark.asyncio
async def test_cancelled_stream_records_cancelled_execution(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)

    async def stream():
        yield AgentChatTextEvent(text="Working")
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        async for _ in persisted_agent_chat_stream(
            s.chat, stream(), s.run, session_factory=factory
        ):
            pass
    assert (await events(factory, s))[-1].event_type == "execution.cancelled"


@pytest.mark.asyncio
async def test_approval_pause_decision_resume_and_idempotent_finish(postgres_engine, monkeypatch):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory.begin() as session:
        prepared = await prepare_runtime(session, s, monkeypatch)
        schema = MCPServerToolSchema(
            workspace_id=s.ws.id,
            installation_id=prepared.installation.id,
            server_name="test/search",
            server_version="1.0.0",
            tool_name="search",
        )
        session.add(schema)
        await session.flush()
        approval = await agents.create_tool_approval(
            session,
            **scope(s),
            agent_id=s.agent.id,
            conversation_id=s.chat.id,
            agent_run_id=s.run.id,
            requested_by_id=None,
            installation_id=prepared.installation.id,
            tool_schema_id=schema.id,
            tool_call_id="provider-call-1",
            tool_name="search",
            arguments={"api_key": "secret"},
        )
        run = await session.get(AgentRun, s.run.id)
        await agents.finish_agent_run(session, run, status="waiting_confirmation")
    async with factory.begin() as session:
        await agents.append_agent_run_step(
            session,
            agent_run_id=s.run.id,
            step_type="tool_approval",
            status="running",
            title="search",
            payload={"approvalId": str(approval.id), "decision": "approve"},
        )
        run = await session.get(AgentRun, s.run.id)
        await agents.mark_agent_run_running(session, run)
        await agents.finish_agent_run(session, run, status="succeeded")
        await agents.finish_agent_run(session, run, status="succeeded")
    rows = await events(factory, s)
    assert [row.event_type for row in rows][-5:] == [
        "approval.requested",
        "execution.paused",
        "approval.granted",
        "execution.resumed",
        "execution.succeeded",
    ]
    assert rows[-5].data["provider_tool_call_id"] == "provider-call-1"
    assert "api_key" not in json.dumps([row.data for row in rows])


@pytest.mark.asyncio
async def test_stateless_messages_and_disabled_capture(postgres_engine, monkeypatch):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory, conversation=False)
    async with factory.begin() as session:
        for step_type in ("model_input", "model_output"):
            await agents.append_agent_run_step(
                session, agent_run_id=s.run.id, step_type=step_type, payload={"content": "private"}
            )
    assert [row.event_type for row in await events(factory, s)] == [
        "execution.started",
        "user.message",
        "agent.response",
    ]
    monkeypatch.setattr(
        capture, "get_settings", lambda: SimpleNamespace(learning_events_enabled=False)
    )
    async with factory.begin() as session:
        run = await session.get(AgentRun, s.run.id)
        await agents.finish_agent_run(session, run, status="succeeded")
    assert len(await events(factory, s)) == 3


@pytest.mark.asyncio
async def test_external_hub_fetch_records_snapshot_not_skill_content(postgres_engine, monkeypatch):
    from app.modules.agents.skills import WARDN_GET_SKILL_TOOL_NAME

    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)

    async def fetch(*args, **kwargs):
        return json.dumps(
            {
                "id": "example/seo/ctr",
                "hash": "a" * 64,
                "skillMarkdown": "private guidance password=secret",
            }
        )

    monkeypatch.setattr(chat_orchestrator, "execute_agent_skill_tool_call_with_context", fetch)

    async def stream():
        async for item in chat_orchestrator.execute_agent_skill_tool_call_stream(
            AgentToolCall(
                call_id="fetch-1",
                name=WARDN_GET_SKILL_TOOL_NAME,
                arguments={"skillId": "example/seo/ctr"},
            )
        ):
            if isinstance(item, chat_orchestrator.AgentChatToolActivityEvent):
                yield item

    async for _ in persisted_agent_chat_stream(s.chat, stream(), s.run, session_factory=factory):
        pass
    rows = [row for row in await events(factory, s) if row.event_type == "skill.external_retrieved"]
    assert len(rows) == 1
    assert rows[0].data["external_skill"] == {"id": "example/seo/ctr", "content_hash": "a" * 64}
    assert "private guidance" not in json.dumps(rows[0].data)


@pytest.mark.asyncio
async def test_cursor_refreshes_when_reusing_session_after_another_consumer(postgres_engine):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    seen = []

    async def consume(session, batch):
        seen.extend(row.id for row in batch)

    async with factory() as first:
        await repository.consume_batch(first, worker_name="reuse", **scope(s), consume=consume)
        cursor = await first.scalar(
            select(LearningWorkerCursor).where(LearningWorkerCursor.workspace_id == s.ws.id)
        )
        await first.commit()
        async with factory.begin() as session:
            await emitter.emit(session, event(s, "later-event"))
        async with factory.begin() as session:
            assert (
                await repository.consume_batch(
                    session, worker_name="reuse", **scope(s), consume=consume
                )
                == 1
            )
        assert (
            await repository.consume_batch(first, worker_name="reuse", **scope(s), consume=consume)
            == 0
        )
        assert cursor.last_sequence == 2
        await first.commit()
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_agent_tool_handoff_uses_fresh_transaction_after_isolated_tracking(
    postgres_engine,
    monkeypatch,
):
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    s = await seed(factory)
    async with factory.begin() as session:
        prepared = await prepare_runtime(session, s, monkeypatch)
        schema = MCPServerToolSchema(
            workspace_id=s.ws.id,
            installation_id=prepared.installation.id,
            server_name="test/search",
            server_version="1.0.0",
            tool_name="search",
        )
        session.add(schema)
        await session.flush()
    manager = SimpleNamespace(
        call_tool=lambda *args, **kwargs: {
            "content": [{"type": "text", "text": "Search results"}],
            "isError": False,
        }
    )
    monkeypatch.setattr(
        tool_execution,
        "call_tool_with_isolated_tracking",
        partial(
            runtime.call_tool_with_isolated_tracking,
            tracking_session_factory=factory,
            manager=manager,
        ),
    )

    async def allowed(*args, **kwargs):
        return SimpleNamespace(
            mode="allow",
            policy_id=None,
            policy_name="test",
            matched_policy_ids=[],
            message="Allowed by test policy",
        )

    monkeypatch.setattr(tool_execution, "evaluate_tool_call_guardrails", allowed)
    tool = AgentRuntimeTool(
        wire_name="search",
        assignment_id=uuid.uuid4(),
        tool_schema=schema,
        installation=prepared.installation,
        server=MCPServerVersion(name="test/search", version="1.0.0"),
    )
    result = await tool_execution.execute_agent_tool_call(
        {"search": tool},
        AgentToolCall(name="search", call_id="provider-1", arguments={"query": "seo"}),
        session_factory=factory,
        **scope(s),
        agent=s.agent,
        conversation=s.chat,
        agent_run=s.run,
    )
    assert result.status == "completed"
    rows = await events(factory, s)
    assert [row.event_type for row in rows][-3:] == [
        "tool.call_started",
        "tool.call_completed",
        "tool.result_observed",
    ]
    assert rows[-1].tool_call_id == rows[-2].tool_call_id
    assert rows[-1].tool_call_id != prepared.invocation_id
