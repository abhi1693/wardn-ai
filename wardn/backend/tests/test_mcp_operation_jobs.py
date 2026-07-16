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
        cleanup_max_attempts=5,
        cleanup_worker_id="",
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


def test_operation_deduplication_key_is_stable_for_equivalent_payloads() -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    first = job_service.operation_deduplication_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        operation="install_server",
        resource_key="server:example",
        request_payload={"version": "1.0.0", "config": {"a": 1, "b": 2}},
    )
    second = job_service.operation_deduplication_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        operation="install_server",
        resource_key="server:example",
        request_payload={"config": {"b": 2, "a": 1}, "version": "1.0.0"},
    )

    assert first == second
    assert len(first) == 64


@pytest.mark.asyncio
async def test_enqueue_operation_job_reuses_active_equivalent_job(monkeypatch) -> None:
    job = make_job(workspace_id=uuid.uuid4())
    seen: dict[str, object] = {}

    async def find_existing(session, deduplication_key):
        seen["deduplication_key"] = deduplication_key
        return job

    async def list_events(session, job_id):
        return []

    monkeypatch.setattr(
        job_service.job_repository,
        "get_active_job_by_deduplication_key",
        find_existing,
    )
    monkeypatch.setattr(job_service.job_repository, "list_job_events", list_events)

    response = await job_service.enqueue_operation_job(
        object(),
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        requested_by_id=job.requested_by_id,
        operation=job.operation,
        resource_key=job.resource_key,
        request_payload=job.request_payload,
        progress_total=4,
    )

    assert response.job_id == job.id
    assert seen["deduplication_key"] == job_service.operation_deduplication_key(
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        operation=job.operation,
        resource_key=job.resource_key,
        request_payload=job.request_payload,
    )


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
