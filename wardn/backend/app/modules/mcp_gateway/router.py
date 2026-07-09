from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.mcp_gateway import service
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_gateway.oauth import bearer_challenge
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.organizations import repository as organizations_repository
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import require_organization_admin, require_workspace_admin
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User, UserAPIToken
from app.modules.users.service import authenticate_api_token

router = APIRouter(prefix="/mcp/gateway", tags=["mcp-gateway"])
workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/mcp/gateway",
    tags=["workspace-mcp-gateway"],
)


def jsonrpc_result(request_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def jsonrpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status.HTTP_200_OK,
    )


async def build_authenticated_gateway_scope(
    session: AsyncSession,
    current_user: User,
    *,
    organization_id: UUID | None,
    workspace_id: UUID | None,
) -> GatewayScope:
    if workspace_id is not None:
        workspace = await organizations_repository.get_workspace_by_id(session, workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError("workspace not found")
        if organization_id is not None and workspace.organization_id != organization_id:
            raise WorkspaceNotFoundError("workspace not found")
        await require_workspace_admin(
            session,
            current_user,
            workspace.organization_id,
            workspace_id,
        )
        return GatewayScope(
            user_id=current_user.id,
            is_superuser=current_user.is_superuser,
            organization_id=workspace.organization_id,
            workspace_id=workspace_id,
        )

    if organization_id is not None:
        await require_organization_admin(session, current_user, organization_id)
        return GatewayScope(
            user_id=current_user.id,
            is_superuser=current_user.is_superuser,
            organization_id=organization_id,
        )

    return GatewayScope(
        user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )


def api_token_scope_ids(values: list[str] | None) -> frozenset[UUID] | None:
    if values is None:
        return None
    parsed = frozenset(UUID(str(value)) for value in values if value)
    return parsed if parsed else None


async def require_gateway_api_token(
    request: Request,
    session: AsyncSession,
    authorization: str | None,
) -> tuple[User, UserAPIToken]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="gateway bearer token required",
            headers={"WWW-Authenticate": bearer_challenge(request)},
        )
    plaintext_token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
    authenticated = await authenticate_api_token(session, plaintext_token)
    if authenticated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid gateway bearer token",
            headers={"WWW-Authenticate": bearer_challenge(request, error="invalid_token")},
        )
    return authenticated


def build_api_token_gateway_scope(user: User, api_token: UserAPIToken) -> GatewayScope:
    return GatewayScope(
        user_id=user.id,
        is_superuser=user.is_superuser,
        organization_ids=api_token_scope_ids(api_token.organization_ids),
        workspace_ids=api_token_scope_ids(api_token.workspace_ids),
    )


async def handle_mcp_gateway_rpc(
    request: Request,
    session: AsyncSession,
    *,
    scope: GatewayScope,
) -> Response:
    try:
        payload = await request.json()
    except ValueError:
        return jsonrpc_error(None, -32700, "Parse error")

    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(None, -32600, "Invalid Request")

    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    if request_id is None and isinstance(method, str) and method.startswith("notifications/"):
        return Response(status_code=status.HTTP_202_ACCEPTED)

    try:
        request_meta = service.request_meta(params)
    except ValueError as exc:
        return jsonrpc_error(request_id, -32602, str(exc))

    if method == "initialize":
        return jsonrpc_result(request_id, service.initialize_result())
    if method == "ping":
        return jsonrpc_result(request_id, service.ping_result())
    if method == "tools/list":
        return jsonrpc_result(request_id, {"tools": service.gateway_tools()})
    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            return jsonrpc_result(
                request_id,
                await service.call_tool(
                    session,
                    tool_name,
                    arguments,
                    scope=scope,
                    request_meta=request_meta,
                ),
            )
        except ValueError as exc:
            return jsonrpc_error(request_id, -32602, str(exc))
        except LookupError as exc:
            return jsonrpc_error(request_id, -32602, str(exc))
        except MCPGatewayUpstreamError as exc:
            return jsonrpc_error(request_id, -32000, str(exc))

    return jsonrpc_error(request_id, -32601, f"Method not found: {method}")


@router.get("", operation_id="mcp_gateway_auth_discovery", include_in_schema=False)
async def mcp_gateway_auth_discovery(request: Request) -> JSONResponse:
    return JSONResponse(
        {"detail": "gateway bearer token required"},
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": bearer_challenge(request)},
    )


@router.post("", operation_id="mcp_gateway_rpc")
async def mcp_gateway_rpc(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    try:
        user, api_token = await require_gateway_api_token(request, session, authorization)
        scope = build_api_token_gateway_scope(user, api_token)
    except ValueError as exc:
        return jsonrpc_error(None, -32602, str(exc))
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        return jsonrpc_error(None, -32602, str(exc))
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        return jsonrpc_error(None, -32603, str(exc))
    return await handle_mcp_gateway_rpc(request, session, scope=scope)


@workspace_router.post("", operation_id="workspace_mcp_gateway_rpc")
async def workspace_mcp_gateway_rpc(
    organization_id: UUID,
    workspace_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        scope = await build_authenticated_gateway_scope(
            session,
            current_user,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        return jsonrpc_error(None, -32602, str(exc))
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        return jsonrpc_error(None, -32603, str(exc))
    return await handle_mcp_gateway_rpc(request, session, scope=scope)
