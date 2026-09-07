import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning.models import LearningEvent, LearningEventStream, LearningWorkerCursor
from app.modules.learning.schemas import EventCreate, EventRead
from app.modules.organizations.models import Workspace


async def require_workspace(
    session: AsyncSession,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    found = await session.scalar(
        select(Workspace.id).where(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
    )
    if found is None:
        raise ValueError("learning workspace not found in organization")


async def append_event(session: AsyncSession, event: EventCreate) -> LearningEvent:
    """Caller validates provenance. Hold the allocator row lock through the caller's commit."""
    allocator = insert(LearningEventStream).values(
        organization_id=event.organization_id,
        workspace_id=event.workspace_id,
        last_sequence=1,
    )
    workspace_sequence = await session.scalar(
        allocator.on_conflict_do_update(
            index_elements=[LearningEventStream.workspace_id],
            set_={"last_sequence": LearningEventStream.last_sequence + 1},
            where=LearningEventStream.organization_id == event.organization_id,
        ).returning(LearningEventStream.last_sequence)
    )
    if workspace_sequence is None:
        raise ValueError("learning stream organization mismatch")
    existing = await session.scalar(
        select(LearningEvent).where(
            LearningEvent.organization_id == event.organization_id,
            LearningEvent.workspace_id == event.workspace_id,
            LearningEvent.idempotency_key == event.idempotency_key,
        )
    )
    if existing is not None:
        # Retrying a source transition must not replace evidence or alias another transition.
        for field in ("execution_id", "execution_kind", "event_type", "source", "tool_call_id"):
            if getattr(existing, field) != getattr(event, field):
                raise ValueError("learning idempotency key conflicts with existing event")
        return existing
    sequence = await session.scalar(
        select(func.max(LearningEvent.sequence_number)).where(
            LearningEvent.organization_id == event.organization_id,
            LearningEvent.workspace_id == event.workspace_id,
            LearningEvent.execution_id == event.execution_id,
        )
    )
    row = LearningEvent(
        **event.model_dump(exclude={"sensitive_paths"}),
        sequence_number=(sequence or 0) + 1,
        workspace_sequence=workspace_sequence,
    )
    session.add(row)
    await session.flush()
    return row


async def list_events(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    after_sequence: int = 0,
    execution_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[LearningEvent]:
    if not 1 <= limit <= 1000 or after_sequence < 0:
        raise ValueError("invalid learning event page")
    statement = select(LearningEvent).where(
        LearningEvent.organization_id == organization_id,
        LearningEvent.workspace_id == workspace_id,
        LearningEvent.workspace_sequence > after_sequence,
    )
    if execution_id is not None:
        statement = statement.where(LearningEvent.execution_id == execution_id)
    return list(
        (
            await session.scalars(statement.order_by(LearningEvent.workspace_sequence).limit(limit))
        ).all()
    )


async def consume_batch(
    session: AsyncSession,
    *,
    worker_name: str,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    consume: Callable[[AsyncSession, list[EventRead]], Awaitable[None]],
    limit: int = 100,
) -> int:
    """Commit derived database writes and cursor together. Caller owns the transaction.

    The callback must use this session and must not commit or perform external effects.
    A crash/exception rolls back both effects and checkpoint. Competing consumers serialize
    on one cursor row; readers never advance beyond an uncommitted event.
    """
    if not worker_name or len(worker_name) > 100:
        raise ValueError("invalid learning worker name")
    await require_workspace(session, organization_id, workspace_id)
    await session.execute(
        insert(LearningWorkerCursor)
        .values(
            worker_name=worker_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            last_sequence=0,
        )
        .on_conflict_do_nothing()
    )
    cursor = (
        await session.scalars(
            select(LearningWorkerCursor)
            .where(
                LearningWorkerCursor.worker_name == worker_name,
                LearningWorkerCursor.organization_id == organization_id,
                LearningWorkerCursor.workspace_id == workspace_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one()
    events = await list_events(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        after_sequence=cursor.last_sequence,
        limit=limit,
    )
    if events:
        await consume(session, [EventRead.model_validate(event) for event in events])
        cursor.last_sequence = events[-1].workspace_sequence
        cursor.last_event_id = events[-1].id
        await session.flush()
    return len(events)
