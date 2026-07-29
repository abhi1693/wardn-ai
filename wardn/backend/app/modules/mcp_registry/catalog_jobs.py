import hashlib
import json
import logging
import uuid
from typing import Any

from app.db.session import AsyncSessionLocal
from app.modules.mcp_registry import repository, service
from app.modules.mcp_registry.exceptions import MCPCatalogSourceNotFoundError
from app.modules.mcp_registry.job_service import enqueue_operation_job
from app.modules.mcp_registry.job_worker import JobProgressReporter, MCPJobExecutionError
from app.modules.mcp_registry.models import MCPCatalogSource, MCPOperationJob
from app.modules.mcp_registry.schemas import MCPOperationJobRead
from app.modules.users.models import User

SYNC_CATALOG_SOURCE_OPERATION = "sync_catalog_source"
logger = logging.getLogger(__name__)


def catalog_sync_log_extra(
    *,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
    source_name: str | None = None,
    provider: str | None = None,
    sync_mode: str | None = None,
    job_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "organization_id": str(organization_id),
        "mcp_catalog_source_id": str(source_id),
    }
    if source_name:
        extra["mcp_catalog_source_name"] = source_name
    if provider:
        extra["mcp_catalog_provider"] = provider
    if sync_mode:
        extra["mcp_catalog_sync_mode"] = sync_mode
    if job_id is not None:
        extra["mcp_job_id"] = str(job_id)
    return extra


def response_job_id(response: Any) -> uuid.UUID | None:
    return getattr(response, "job_id", None)


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
    response = await enqueue_operation_job(
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
    logger.info(
        "Queued MCP catalog source sync.",
        extra=catalog_sync_log_extra(
            organization_id=organization_id,
            source_id=source.id,
            source_name=source.name,
            provider=source.provider,
            sync_mode=source.sync_mode,
            job_id=response_job_id(response),
        ),
    )
    return response


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
    logger.info(
        "Preparing MCP catalog source sync job.",
        extra={
            **catalog_sync_log_extra(
                organization_id=job.organization_id,
                source_id=source_id,
                job_id=job.id,
            ),
            "mcp_source_revision_expected": bool(expected_revision),
        },
    )
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
        logger.info(
            "Synchronizing MCP catalog source.",
            extra=catalog_sync_log_extra(
                organization_id=job.organization_id,
                source_id=source.id,
                source_name=source.name,
                provider=source.provider,
                sync_mode=source.sync_mode,
                job_id=job.id,
            ),
        )
        try:
            result = await service.sync_catalog_source(
                session,
                job.organization_id,
                source_id,
            )
        except ValueError as exc:
            await session.commit()
            logger.warning(
                "MCP catalog source sync job failed.",
                extra={
                    **catalog_sync_log_extra(
                        organization_id=job.organization_id,
                        source_id=source.id,
                        source_name=source.name,
                        provider=source.provider,
                        sync_mode=source.sync_mode,
                        job_id=job.id,
                    ),
                    "error_type": exc.__class__.__name__,
                },
            )
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
    result_source = getattr(result, "source", None)
    logger.info(
        "Synchronized MCP catalog source.",
        extra={
            **catalog_sync_log_extra(
                organization_id=job.organization_id,
                source_id=source_id,
                source_name=getattr(result_source, "name", None),
                provider=getattr(result_source, "provider", None),
                sync_mode=getattr(result_source, "sync_mode", None),
                job_id=job.id,
            ),
            "mcp_catalog_synced_count": result.synced_count,
        },
    )
    return result.model_dump(mode="json", by_alias=True)
