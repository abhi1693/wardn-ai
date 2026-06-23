from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.agents.exceptions import (
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.schemas import (
    AgentChatRequest,
    AgentCreate,
    AgentListResponse,
    AgentRead,
    AgentToolAssignmentUpdate,
    AgentToolListResponse,
    AgentUpdate,
)
from app.modules.agents.service import (
    AgentChatProviderError,
    create_agent,
    delete_agent,
    get_agent,
    list_agent_tools,
    list_agents,
    replace_agent_tools,
    stream_agent_chat,
    update_agent,
)
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["agents"])


async def prime_stream(stream):
    try:
        first_chunk = await anext(stream)
    except StopAsyncIteration:
        first_chunk = None

    async def iterator():
        if first_chunk:
            yield first_chunk
        async for chunk in stream:
            yield chunk

    return iterator()


def raise_access_error(exc: Exception) -> None:
    if isinstance(exc, (OrganizationNotFoundError, WorkspaceNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, (OrganizationAccessDeniedError, WorkspaceAccessDeniedError)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, (InvalidAgentScopeError, InvalidAgentToolAssignmentError)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@router.get(
    "",
    response_model=AgentListResponse,
    operation_id="agents_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_agents_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentListResponse:
    try:
        return await list_agents(session, current_user, organization_id)
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="agents_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_agent_route(
    organization_id: UUID,
    payload: AgentCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRead:
    try:
        response = await create_agent(session, current_user, organization_id, payload)
    except DuplicateAgentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response


@router.get(
    "/{agent_id}",
    response_model=AgentRead,
    operation_id="agents_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_agent_route(
    organization_id: UUID,
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRead:
    try:
        return await get_agent(session, current_user, organization_id, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.patch(
    "/{agent_id}",
    response_model=AgentRead,
    operation_id="agents_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_agent_route(
    organization_id: UUID,
    agent_id: UUID,
    payload: AgentUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRead:
    try:
        response = await update_agent(session, current_user, organization_id, agent_id, payload)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateAgentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="agents_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_agent_route(
    organization_id: UUID,
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        await delete_agent(session, current_user, organization_id, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()


@router.post(
    "/{agent_id}/chat",
    operation_id="agents_chat",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "content": {"text/plain": {"schema": {"type": "string"}}},
            "description": "Successful Response",
        },
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def chat_agent_route(
    organization_id: UUID,
    agent_id: UUID,
    payload: AgentChatRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    try:
        stream = await stream_agent_chat(session, current_user, organization_id, agent_id, payload)
        stream = await prime_stream(stream)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentChatProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    return StreamingResponse(stream, media_type="text/plain; charset=utf-8")


@router.get(
    "/{agent_id}/tools",
    response_model=AgentToolListResponse,
    operation_id="agents_list_tools",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_agent_tools_route(
    organization_id: UUID,
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentToolListResponse:
    try:
        return await list_agent_tools(session, current_user, organization_id, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise


@router.put(
    "/{agent_id}/tools",
    response_model=AgentToolListResponse,
    operation_id="agents_replace_tools",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def replace_agent_tools_route(
    organization_id: UUID,
    agent_id: UUID,
    payload: AgentToolAssignmentUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentToolListResponse:
    try:
        response = await replace_agent_tools(
            session,
            current_user,
            organization_id,
            agent_id,
            payload,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_access_error(exc)
        raise
    await session.commit()
    return response
