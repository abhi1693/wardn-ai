import uuid
from datetime import UTC, datetime

import pytest

from app.modules.mcp_registry import job_service
from app.modules.mcp_registry.exceptions import MCPOperationJobNotFoundError
from app.modules.mcp_registry.models import MCPOperationJob, MCPOperationJobEvent


def make_job(*, workspace_id: uuid.UUID | None = None) -> MCPOperationJob:
    timestamp = datetime(2026, 7, 16, 10, 30, tzinfo=UTC)
    return MCPOperationJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        workspace_id=workspace_id,
        requested_by_id=uuid.uuid4(),
        operation="install_server",
        resource_key="workspace:test/server:example",
        deduplication_key="dedupe-key",
        status="running",
        request_payload={"version": "1.2.3"},
        result={},
        progress_current=2,
        progress_total=4,
        progress_message="Installing package",
        attempt_count=1,
        max_attempts=3,
        available_at=timestamp,
        worker_id="worker-1",
        error_code="",
        error_message="",
        cleanup_status="not_required",
        cleanup_payload={},
        cleanup_attempt_count=0,
        cleanup_error="",
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_job_response_includes_persisted_progress_and_events() -> None:
    workspace_id = uuid.uuid4()
    job = make_job(workspace_id=workspace_id)
    event = MCPOperationJobEvent(
        id=uuid.uuid4(),
        job_id=job.id,
        event_type="progress",
        level="info",
        message="Installing package",
        progress_current=2,
        progress_total=4,
        details={"phase": "install"},
        created_at=job.created_at,
    )

    response = job_service.job_response(job, [event]).model_dump(by_alias=True)

    assert response["jobId"] == job.id
    assert response["workspaceId"] == workspace_id
    assert response["status"] == "running"
    assert response["progressCurrent"] == 2
    assert response["progressMessage"] == "Installing package"
    assert response["events"] == [
        {
            "id": event.id,
            "eventType": "progress",
            "level": "info",
            "message": "Installing package",
            "progressCurrent": 2,
            "progressTotal": 4,
            "details": {"phase": "install"},
            "createdAt": job.created_at,
        }
    ]


@pytest.mark.asyncio
async def test_get_operation_job_enforces_scope_and_loads_events(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    job = make_job(workspace_id=workspace_id)
    job.organization_id = organization_id
    calls: dict[str, object] = {}

    async def fake_get_job(session, job_id, *, organization_id, workspace_id):
        calls["get"] = (session, job_id, organization_id, workspace_id)
        return job

    async def fake_list_job_events(session, job_id):
        calls["events"] = (session, job_id)
        return []

    monkeypatch.setattr(job_service.job_repository, "get_job", fake_get_job)
    monkeypatch.setattr(job_service.job_repository, "list_job_events", fake_list_job_events)
    session = object()

    response = await job_service.get_operation_job(
        session,
        job.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    assert response.job_id == job.id
    assert calls["get"] == (session, job.id, organization_id, workspace_id)
    assert calls["events"] == (session, job.id)


@pytest.mark.asyncio
async def test_get_operation_job_hides_jobs_outside_scope(monkeypatch) -> None:
    async def fake_get_job(*args, **kwargs):
        return None

    monkeypatch.setattr(job_service.job_repository, "get_job", fake_get_job)

    with pytest.raises(MCPOperationJobNotFoundError, match="not found"):
        await job_service.get_operation_job(
            object(),
            uuid.uuid4(),
            organization_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
        )
