import asyncio
import json
from typing import Annotated
from uuid import UUID

import typer

from app.db.session import AsyncSessionLocal
from app.modules.learning.repository import list_events, require_workspace
from app.modules.learning.schemas import EventRead


async def inspect_events(
    organization_id: UUID,
    workspace_id: UUID,
    execution_id: UUID | None,
    after_sequence: int,
    limit: int,
) -> dict:
    async with AsyncSessionLocal() as session:
        await require_workspace(session, organization_id, workspace_id)
        rows = await list_events(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        return {
            "events": [EventRead.model_validate(row).model_dump(mode="json") for row in rows],
            "next_after_sequence": rows[-1].workspace_sequence if rows else after_sequence,
        }


def register_learning_commands(app: typer.Typer) -> None:
    @app.command("learningevents")
    def learning_events(
        organization_id: Annotated[UUID, typer.Option()],
        workspace_id: Annotated[UUID, typer.Option()],
        execution_id: Annotated[UUID | None, typer.Option()] = None,
        after_sequence: Annotated[int, typer.Option(min=0)] = 0,
        limit: Annotated[int, typer.Option(min=1, max=1000)] = 100,
    ) -> None:
        """Inspect one scoped page of execution evidence (operator/database access required)."""
        result = asyncio.run(
            inspect_events(
                organization_id,
                workspace_id,
                execution_id,
                after_sequence,
                limit,
            )
        )
        typer.echo(json.dumps(result, indent=2))
