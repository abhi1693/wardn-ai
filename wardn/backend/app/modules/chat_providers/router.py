from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.chat_providers.exceptions import ChatProviderWebhookAuthError
from app.modules.chat_providers.schemas import (
    ChatProviderConnectionCreate,
    ChatProviderConnectionListResponse,
    ChatProviderConnectionRead,
    ChatProviderConnectionUpdate,
    ChatProviderPairingStatusResponse,
    ChatProviderWebhookResponse,
)
from app.modules.chat_providers.service import (
    create_workspace_chat_provider_connection,
    delete_workspace_chat_provider_connection,
    get_workspace_chat_provider_connection,
    get_workspace_chat_provider_pairing_status,
    handle_telegram_webhook,
    handle_whatsapp_local_webhook,
    list_workspace_chat_provider_connections,
    refresh_workspace_chat_provider_pairing_qr,
    update_workspace_chat_provider_connection,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/chat-providers",
    tags=["workspace-chat-providers"],
)

webhook_router = APIRouter(
    prefix="/chat-providers",
    tags=["chat-provider-webhooks"],
)


@workspace_router.get(
    "",
    response_model=ChatProviderConnectionListResponse,
    operation_id="workspace_chat_providers_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_chat_provider_connections_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatProviderConnectionListResponse:
    return await list_workspace_chat_provider_connections(
        session,
        current_user,
        organization_id,
        workspace_id,
    )


@workspace_router.post(
    "",
    response_model=ChatProviderConnectionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="workspace_chat_providers_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_workspace_chat_provider_connection_route(
    organization_id: UUID,
    workspace_id: UUID,
    payload: ChatProviderConnectionCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatProviderConnectionRead:
    return await create_workspace_chat_provider_connection(
        session,
        current_user,
        organization_id,
        workspace_id,
        payload,
    )


@workspace_router.get(
    "/{connection_id}",
    response_model=ChatProviderConnectionRead,
    operation_id="workspace_chat_providers_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_chat_provider_connection_route(
    organization_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatProviderConnectionRead:
    return await get_workspace_chat_provider_connection(
        session,
        current_user,
        organization_id,
        workspace_id,
        connection_id,
    )


@workspace_router.patch(
    "/{connection_id}",
    response_model=ChatProviderConnectionRead,
    operation_id="workspace_chat_providers_update",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_workspace_chat_provider_connection_route(
    organization_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
    payload: ChatProviderConnectionUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatProviderConnectionRead:
    return await update_workspace_chat_provider_connection(
        session,
        current_user,
        organization_id,
        workspace_id,
        connection_id,
        payload,
    )


@workspace_router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_chat_providers_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_workspace_chat_provider_connection_route(
    organization_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await delete_workspace_chat_provider_connection(
        session,
        current_user,
        organization_id,
        workspace_id,
        connection_id,
    )


@workspace_router.get(
    "/{connection_id}/pairing",
    response_model=ChatProviderPairingStatusResponse,
    operation_id="workspace_chat_providers_pairing_status",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_workspace_chat_provider_pairing_status_route(
    organization_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatProviderPairingStatusResponse:
    return await get_workspace_chat_provider_pairing_status(
        session,
        current_user,
        organization_id,
        workspace_id,
        connection_id,
    )


@workspace_router.post(
    "/{connection_id}/pairing/refresh",
    response_model=ChatProviderPairingStatusResponse,
    operation_id="workspace_chat_providers_refresh_pairing_qr",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def refresh_workspace_chat_provider_pairing_qr_route(
    organization_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatProviderPairingStatusResponse:
    return await refresh_workspace_chat_provider_pairing_qr(
        session,
        current_user,
        organization_id,
        workspace_id,
        connection_id,
    )


@webhook_router.post(
    "/telegram/{connection_id}/webhook",
    response_model=ChatProviderWebhookResponse,
    operation_id="chat_provider_webhooks_telegram_receive",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def receive_telegram_webhook_route(
    connection_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_telegram_bot_api_secret_token: Annotated[
        str | None,
        Header(alias="X-Telegram-Bot-Api-Secret-Token"),
    ] = None,
) -> ChatProviderWebhookResponse:
    body = await request.body()
    try:
        return await handle_telegram_webhook(
            session,
            connection_id=connection_id,
            body=body,
            secret_token_header=x_telegram_bot_api_secret_token,
        )
    except ChatProviderWebhookAuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@webhook_router.post(
    "/whatsapp-local/{connection_id}/webhook",
    response_model=ChatProviderWebhookResponse,
    operation_id="chat_provider_webhooks_whatsapp_local_receive",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def receive_whatsapp_local_webhook_route(
    connection_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_wardn_chat_provider_secret: Annotated[
        str | None,
        Header(alias="X-Wardn-Chat-Provider-Secret"),
    ] = None,
) -> ChatProviderWebhookResponse:
    body = await request.body()
    try:
        return await handle_whatsapp_local_webhook(
            session,
            connection_id=connection_id,
            body=body,
            secret_header=x_wardn_chat_provider_secret,
        )
    except ChatProviderWebhookAuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
