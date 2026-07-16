from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.observability import service
from app.modules.observability.schemas import (
    LLMModelPriceCreate,
    LLMModelPriceListResponse,
    LLMModelPricePrefillResponse,
    LLMModelPriceRead,
    LLMModelPriceUpdate,
    LLMUsageListResponse,
    MCPToolUsageListResponse,
    UsageSummaryResponse,
)
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_member,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/observability",
    tags=["workspace-observability"],
)
organization_router = APIRouter(
    prefix="/organizations/{organization_id}/observability",
    tags=["organization-observability"],
)
usage_router = APIRouter(tags=["usage"])


async def require_organization_member_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
) -> None:
    try:
        await require_organization_member(session, current_user, organization_id)
    except OrganizationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def require_organization_admin_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
) -> None:
    try:
        await require_organization_admin(session, current_user, organization_id)
    except OrganizationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def require_workspace_member_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
    workspace_id: UUID,
) -> None:
    try:
        await require_workspace_member(session, current_user, organization_id, workspace_id)
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@usage_router.get(
    "/organizations/{organization_id}/usage/summary",
    response_model=UsageSummaryResponse,
    operation_id="organization_usage_summary",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def organization_usage_summary_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UsageSummaryResponse:
    await require_organization_admin_or_404(session, current_user, organization_id)
    return await service.organization_usage_summary(session, organization_id=organization_id)


@usage_router.get(
    "/organizations/{organization_id}/workspaces/{workspace_id}/usage/summary",
    response_model=UsageSummaryResponse,
    operation_id="workspace_usage_summary",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def workspace_usage_summary_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UsageSummaryResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.workspace_usage_summary(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


@usage_router.get(
    "/me/usage",
    response_model=UsageSummaryResponse,
    operation_id="me_usage_summary",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def me_usage_summary_route(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UsageSummaryResponse:
    return await service.user_usage_summary(session, user_id=current_user.id)


@workspace_router.get(
    "/mcp-tool-usage",
    response_model=MCPToolUsageListResponse,
    operation_id="workspace_observability_list_mcp_tool_usage",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_mcp_tool_usage_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MCPToolUsageListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.list_workspace_mcp_tool_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
    )


@workspace_router.get(
    "/llm-usage",
    response_model=LLMUsageListResponse,
    operation_id="workspace_observability_list_llm_usage",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_llm_usage_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> LLMUsageListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.list_workspace_llm_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
    )


@organization_router.get(
    "/llm/model-prices",
    response_model=LLMModelPriceListResponse,
    operation_id="organization_observability_list_llm_model_prices",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_llm_model_prices_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMModelPriceListResponse:
    await require_organization_member_or_404(session, current_user, organization_id)
    return await service.list_llm_model_prices(session)


@organization_router.post(
    "/llm/model-prices",
    response_model=LLMModelPriceRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="organization_observability_create_llm_model_price",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_llm_model_price_route(
    organization_id: UUID,
    payload: LLMModelPriceCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMModelPriceRead:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await service.create_llm_model_price(session, payload)
    except service.DuplicateLLMModelPriceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return response


@organization_router.get(
    "/llm/model-prices/prefill",
    response_model=LLMModelPricePrefillResponse,
    operation_id="organization_observability_prefill_llm_model_price",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def prefill_llm_model_price_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    provider: Annotated[str, Query(min_length=1, max_length=50)],
    model: Annotated[str, Query(min_length=1, max_length=255)],
) -> LLMModelPricePrefillResponse:
    await require_organization_member_or_404(session, current_user, organization_id)
    try:
        return await service.fetch_openrouter_model_prices(provider=provider, model=model)
    except service.LLMModelPricePrefillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@organization_router.patch(
    "/llm/model-prices/{price_id}",
    response_model=LLMModelPriceRead,
    operation_id="organization_observability_update_llm_model_price",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_llm_model_price_route(
    organization_id: UUID,
    price_id: UUID,
    payload: LLMModelPriceUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LLMModelPriceRead:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await service.update_llm_model_price(session, price_id=price_id, payload=payload)
    except service.LLMModelPriceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DuplicateLLMModelPriceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return response


@organization_router.delete(
    "/llm/model-prices/{price_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="organization_observability_delete_llm_model_price",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_llm_model_price_route(
    organization_id: UUID,
    price_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        await service.delete_llm_model_price(session, price_id=price_id)
    except service.LLMModelPriceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
