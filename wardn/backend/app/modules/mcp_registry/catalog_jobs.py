import hashlib
import json
import uuid

from app.db.session import AsyncSessionLocal
from app.modules.mcp_registry import repository, service
from app.modules.mcp_registry.exceptions import MCPCatalogSourceNotFoundError
from app.modules.mcp_registry.job_service import enqueue_operation_job
from app.modules.mcp_registry.job_worker import JobProgressReporter, MCPJobExecutionError
from app.modules.mcp_registry.models import MCPCatalogSource, MCPOperationJob
from app.modules.mcp_registry.schemas import MCPOperationJobRead
from app.modules.users.models import User

SYNC_CATALOG_SOURCE_OPERATION = "sync_catalog_source"


def catalog_source_resource_key(
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
) -> str:
    return f"organization:{organization_id}:mcp-catalog-source:{source_id}"


def catalog_source_revision(source: MCPCatalogSource) -> str:
    configuration = json.dumps(
        {
            "provider": source.provider,
            "baseUrl": source.base_url,
            "tenantId": source.tenant_id,
            "syncMode": source.sync_mode,
            "isEnabled": source.is_enabled,
            "authSecretHandleId": (
                str(source.auth_secret_handle_id) if source.auth_secret_handle_id else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(configuration.encode()).hexdigest()


async def enqueue_catalog_source_sync(
    session,
    *,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User,
) -> MCPOperationJobRead:
    source = await repository.get_catalog_source(
        session,
        source_id,
        organization_id=organization_id,
    )
    if source is None:
        raise MCPCatalogSourceNotFoundError("catalog source not found")
    if not source.is_enabled:
        raise ValueError("catalog source is disabled")
    return await enqueue_operation_job(
        session,
        organization_id=organization_id,
        workspace_id=None,
        requested_by_id=user.id,
        operation=SYNC_CATALOG_SOURCE_OPERATION,
        resource_key=catalog_source_resource_key(organization_id, source_id),
        request_payload={
            "sourceId": str(source.id),
            "sourceRevision": catalog_source_revision(source),
        },
        progress_total=3,
    )


async def execute_catalog_source_sync(
    job: MCPOperationJob,
    reporter: JobProgressReporter,
) -> dict:
    try:
        source_id = uuid.UUID(str(job.request_payload.get("sourceId") or ""))
    except ValueError as exc:
        raise MCPJobExecutionError(
            "Catalog sync job payload is invalid",
            code="invalid_catalog_sync_request",
            retryable=False,
        ) from exc
    expected_revision = str(job.request_payload.get("sourceRevision") or "")
    await reporter.update(
        1,
        3,
        "Preparing catalog synchronization",
        details={"sourceId": str(source_id), "phase": "prepare"},
    )
    async with AsyncSessionLocal() as session:
        source = await repository.get_catalog_source(
            session,
            source_id,
            organization_id=job.organization_id,
        )
        if source is None:
            raise MCPJobExecutionError(
                "Catalog source no longer exists",
                code="catalog_source_not_found",
                retryable=False,
            )
        if not source.is_enabled:
            raise MCPJobExecutionError(
                "Catalog source is disabled",
                code="catalog_source_disabled",
                retryable=False,
            )
        if expected_revision and catalog_source_revision(source) != expected_revision:
            raise MCPJobExecutionError(
                "Catalog source changed after this synchronization was queued",
                code="catalog_source_changed",
                retryable=False,
            )
        await reporter.update(
            2,
            3,
            f"Synchronizing {source.name}",
            details={"sourceId": str(source_id), "phase": "sync"},
        )
        try:
            result = await service.sync_catalog_source(
                session,
                job.organization_id,
                source_id,
            )
        except ValueError as exc:
            await session.commit()
            raise MCPJobExecutionError(
                str(exc),
                code="catalog_sync_failed",
                retryable=True,
            ) from exc
        await session.commit()

    await reporter.update(
        3,
        3,
        f"Synchronized {result.synced_count} server definitions",
        details={"sourceId": str(source_id), "phase": "complete"},
    )
    return result.model_dump(mode="json", by_alias=True)
