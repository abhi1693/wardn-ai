from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.limits.exceptions import (
    InvalidLimitKeyError,
    InvalidLimitScopeError,
    LimitAccessDeniedError,
    LimitNotFoundError,
)
from app.modules.limits.schemas import (
    ResourceLimitListResponse,
    ResourceLimitRead,
    ResourceLimitUpsert,
)
from app.modules.limits.service import (
    delete_resource_limit,
    list_resource_limits,
    upsert_resource_limit,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/limits", tags=["limits"])


@router.get(
    "",
    response_model=ResourceLimitListResponse,
    operation_id="limits_list",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def list_limits_route(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    scope_type: Annotated[str | None, Query(alias="scopeType")] = None,
    scope_id: Annotated[UUID | None, Query(alias="scopeId")] = None,
    limit_key: Annotated[str | None, Query(alias="limitKey")] = None,
) -> ResourceLimitListResponse:
    try:
        return await list_resource_limits(
            session,
            current_user,
            scope_type=scope_type,
            scope_id=scope_id,
            limit_key=limit_key,
        )
    except LimitAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (InvalidLimitScopeError, InvalidLimitKeyError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put(
    "",
    response_model=ResourceLimitRead,
    operation_id="limits_upsert",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def upsert_limit_route(
    payload: ResourceLimitUpsert,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ResourceLimitRead:
    try:
        response = await upsert_resource_limit(session, current_user, payload)
    except LimitAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (InvalidLimitScopeError, InvalidLimitKeyError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return response


@router.delete(
    "/{limit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="limits_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_limit_route(
    limit_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        await delete_resource_limit(session, current_user, limit_id)
    except LimitAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LimitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
