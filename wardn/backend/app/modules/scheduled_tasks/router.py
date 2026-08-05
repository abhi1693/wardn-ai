from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.scheduled_tasks.schemas import (
    WorkspaceScheduledTaskCreate,
    WorkspaceScheduledTaskListResponse,
    WorkspaceScheduledTaskRead,
    WorkspaceScheduledTaskRouteTestRequest,
    WorkspaceScheduledTaskRouteTestResponse,
    WorkspaceScheduledTaskRunListResponse,
    WorkspaceScheduledTaskRunRead,
    WorkspaceScheduledTaskSchedulePreviewRequest,
    WorkspaceScheduledTaskSchedulePreviewResponse,
    WorkspaceScheduledTaskUpdate,
)
from app.modules.scheduled_tasks.service import (
    create_workspace_scheduled_task,
    delete_workspace_scheduled_task,
    enqueue_workspace_scheduled_task_run,
    get_workspace_scheduled_task,
    get_workspace_scheduled_task_run,
    list_workspace_scheduled_task_runs,
    list_workspace_scheduled_tasks,
    preview_workspace_scheduled_task_schedules,
    retry_workspace_scheduled_task_delivery,
    test_workspace_scheduled_task_route,
    update_workspace_scheduled_task,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/scheduled-tasks",
    tags=["workspace-scheduled-tasks"],
)


@workspace_router.get(
    "",
    response_model=WorkspaceScheduledTaskListResponse,
    operation_id="workspace_scheduled_tasks_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_scheduled_tasks_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskListResponse:
    return await list_workspace_scheduled_tasks(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@workspace_router.post(
    "",
    response_model=WorkspaceScheduledTaskRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="workspace_scheduled_tasks_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_workspace_scheduled_task_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: WorkspaceScheduledTaskCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRead:
    return await create_workspace_scheduled_task(
        session,
        current_user,
        organization_id,
        workspace_id,
        payload,
    )


@workspace_router.post(
    "/preview",
    response_model=WorkspaceScheduledTaskSchedulePreviewResponse,
    operation_id="workspace_scheduled_tasks_preview",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def preview_workspace_scheduled_task_schedules_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: WorkspaceScheduledTaskSchedulePreviewRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskSchedulePreviewResponse:
    return await preview_workspace_scheduled_task_schedules(
        session,
        current_user,
        organization_id,
        workspace_id,
        payload,
    )


@workspace_router.post(
    "/test-route",
    response_model=WorkspaceScheduledTaskRouteTestResponse,
    operation_id="workspace_scheduled_tasks_test_route",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def test_workspace_scheduled_task_route_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: WorkspaceScheduledTaskRouteTestRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRouteTestResponse:
    return await test_workspace_scheduled_task_route(
        session,
        current_user,
        organization_id,
        workspace_id,
        payload,
    )


@workspace_router.get(
    "/runs",
    response_model=WorkspaceScheduledTaskRunListResponse,
    operation_id="workspace_scheduled_tasks_list_runs",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_scheduled_task_runs_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    task_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkspaceScheduledTaskRunListResponse:
    return await list_workspace_scheduled_task_runs(
        session,
        current_user,
        organization_id,
        workspace_id,
        task_id,
        limit=limit,
    )


@workspace_router.get(
    "/runs/{run_id}",
    response_model=WorkspaceScheduledTaskRunRead,
    operation_id="workspace_scheduled_tasks_get_run",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_scheduled_task_run_route(
    organization_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRunRead:
    return await get_workspace_scheduled_task_run(
        session,
        current_user,
        organization_id,
        workspace_id,
        run_id,
    )


@workspace_router.get(
    "/{task_id}",
    response_model=WorkspaceScheduledTaskRead,
    operation_id="workspace_scheduled_tasks_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_scheduled_task_route(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRead:
    return await get_workspace_scheduled_task(
        session,
        current_user,
        organization_id,
        workspace_id,
        task_id,
    )


@workspace_router.patch(
    "/{task_id}",
    response_model=WorkspaceScheduledTaskRead,
    operation_id="workspace_scheduled_tasks_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_workspace_scheduled_task_route(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    payload: WorkspaceScheduledTaskUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRead:
    return await update_workspace_scheduled_task(
        session,
        current_user,
        organization_id,
        workspace_id,
        task_id,
        payload,
    )


@workspace_router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_scheduled_tasks_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_workspace_scheduled_task_route(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await delete_workspace_scheduled_task(
        session,
        current_user,
        organization_id,
        workspace_id,
        task_id,
    )


@workspace_router.post(
    "/{task_id}/runs",
    response_model=WorkspaceScheduledTaskRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="workspace_scheduled_tasks_run_now",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def run_workspace_scheduled_task_now_route(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRunRead:
    return await enqueue_workspace_scheduled_task_run(
        session,
        current_user,
        organization_id,
        workspace_id,
        task_id,
    )


@workspace_router.post(
    "/{task_id}/runs/{run_id}/deliveries/{delivery_id}/retry",
    response_model=WorkspaceScheduledTaskRunRead,
    operation_id="workspace_scheduled_tasks_retry_delivery",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def retry_workspace_scheduled_task_delivery_route(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    run_id: UUID,
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkspaceScheduledTaskRunRead:
    return await retry_workspace_scheduled_task_delivery(
        session,
        current_user,
        organization_id,
        workspace_id,
        task_id,
        run_id,
        delivery_id,
    )
