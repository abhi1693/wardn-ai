from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.agents.schemas import (
    AgentAvailableToolListResponse,
    AgentChatRequest,
    AgentConversationResponse,
    AgentCreate,
    AgentListResponse,
    AgentRead,
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentToolApprovalDecisionRequest,
    AgentToolApprovalDecisionResponse,
    AgentToolAssignmentUpdate,
    AgentToolListResponse,
    AgentUpdate,
)
from app.modules.agents.service import (
    create_workspace_agent,
    decide_agent_tool_approval,
    delete_agent,
    get_agent,
    get_workspace_agent_run,
    get_workspace_conversation,
    list_agent_tools,
    list_agents,
    list_available_agent_tools,
    list_workspace_agent_runs,
    quick_start_workspace_agent,
    replace_agent_tools,
    stream_agent_chat,
    update_agent,
)
from app.modules.users.dependencies import get_current_user, get_stream_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/agents",
    tags=["workspace-agents"],
)

workspace_runs_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/agent-runs",
    tags=["workspace-agent-runs"],
)


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


@workspace_router.get(
    "",
    response_model=AgentListResponse,
    operation_id="workspace_agents_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_agents_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AgentListResponse:
    return await list_agents(
        session,
        current_user,
        organization_id,
        workspace_id,
        cursor=cursor,
        limit=limit,
    )


@workspace_router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="workspace_agents_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_workspace_agent_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: AgentCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRead:
    return await create_workspace_agent(
        session,
        current_user,
        organization_id,
        workspace_id,
        payload,
    )


@workspace_router.post(
    "/quick-start",
    response_model=AgentConversationResponse,
    operation_id="workspace_agents_quick_start",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def quick_start_workspace_agent_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentConversationResponse:
    return await quick_start_workspace_agent(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@workspace_router.get(
    "/conversations/{conversation_id}",
    response_model=AgentConversationResponse,
    operation_id="workspace_agents_get_conversation",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_conversation_route(
    organization_id: UUID,
    workspace_id: UUID,
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentConversationResponse:
    return await get_workspace_conversation(
        session,
        current_user,
        organization_id,
        workspace_id,
        conversation_id,
    )


@workspace_runs_router.get(
    "",
    response_model=AgentRunListResponse,
    operation_id="workspace_agent_runs_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_agent_runs_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRunListResponse:
    return await list_workspace_agent_runs(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@workspace_runs_router.get(
    "/{agent_run_id}",
    response_model=AgentRunDetailResponse,
    operation_id="workspace_agent_runs_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_agent_run_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRunDetailResponse:
    return await get_workspace_agent_run(
        session,
        current_user,
        organization_id,
        workspace_id,
        agent_run_id,
    )


@workspace_router.get(
    "/available-tools",
    response_model=AgentAvailableToolListResponse,
    operation_id="workspace_agents_list_available_tools",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_agent_available_tools_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentAvailableToolListResponse:
    return await list_available_agent_tools(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@workspace_router.get(
    "/{agent_id}",
    response_model=AgentRead,
    operation_id="workspace_agents_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_agent_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRead:
    return await get_agent(session, current_user, organization_id, agent_id, workspace_id)


@workspace_router.patch(
    "/{agent_id}",
    response_model=AgentRead,
    operation_id="workspace_agents_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_workspace_agent_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    payload: AgentUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRead:
    workspace_payload = payload.model_copy(
        update={"scope": "workspace", "workspace_id": workspace_id}
    )
    return await update_agent(
        session,
        current_user,
        organization_id,
        agent_id,
        workspace_payload,
        workspace_id=workspace_id,
    )


@workspace_router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_agents_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_workspace_agent_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await delete_agent(
        session,
        current_user,
        organization_id,
        agent_id,
        workspace_id=workspace_id,
    )


@workspace_router.post(
    "/{agent_id}/chat",
    operation_id="workspace_agents_chat",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "description": "Successful Response",
        },
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def chat_workspace_agent_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    payload: AgentChatRequest,
    session: Annotated[
        AsyncSession,
        Depends(get_db_session, scope="function"),
    ],
    current_user: Annotated[User, Depends(get_stream_current_user)],
) -> StreamingResponse:
    stream = await stream_agent_chat(
        session,
        current_user,
        organization_id,
        agent_id,
        payload,
        workspace_id=workspace_id,
    )
    stream = await prime_stream(stream)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Vercel-AI-UI-Message-Stream": "v1",
        },
    )


@workspace_router.post(
    "/{agent_id}/tool-approvals/{approval_id}",
    response_model=AgentToolApprovalDecisionResponse,
    operation_id="workspace_agents_decide_tool_approval",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def decide_workspace_agent_tool_approval_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    approval_id: UUID,
    payload: AgentToolApprovalDecisionRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentToolApprovalDecisionResponse:
    return await decide_agent_tool_approval(
        session,
        current_user,
        organization_id,
        workspace_id,
        agent_id,
        approval_id,
        payload,
    )


@workspace_router.get(
    "/{agent_id}/tools",
    response_model=AgentToolListResponse,
    operation_id="workspace_agents_list_tools",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_agent_tools_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentToolListResponse:
    return await list_agent_tools(
        session,
        current_user,
        organization_id,
        agent_id,
        workspace_id=workspace_id,
    )


@workspace_router.put(
    "/{agent_id}/tools",
    response_model=AgentToolListResponse,
    operation_id="workspace_agents_replace_tools",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def replace_workspace_agent_tools_route(
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    payload: AgentToolAssignmentUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentToolListResponse:
    return await replace_agent_tools(
        session,
        current_user,
        organization_id,
        agent_id,
        payload,
        workspace_id=workspace_id,
    )
