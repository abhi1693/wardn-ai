from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.mcp_gateway import service
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
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
from app.modules.users.models import User

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


def choose_scope_id(
    query_value: UUID | None,
    header_value: UUID | None,
    *,
    name: str,
) -> UUID | None:
    if query_value is not None and header_value is not None and query_value != header_value:
        raise ValueError(f"{name} query parameter and header do not match")
    return query_value or header_value


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


async def build_common_gateway_scope(
    session: AsyncSession,
    *,
    organization_id: UUID | None,
    workspace_id: UUID | None,
) -> GatewayScope:
    if organization_id is not None and workspace_id is not None:
        workspace = await organizations_repository.get_workspace_by_id(session, workspace_id)
        if workspace is None or workspace.organization_id != organization_id:
            raise WorkspaceNotFoundError("workspace not found")

    return GatewayScope(
        user_id=UUID(int=0),
        is_superuser=True,
        organization_id=organization_id,
        workspace_id=workspace_id,
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

    if method == "initialize":
        return jsonrpc_result(request_id, service.initialize_result())
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
                ),
            )
        except ValueError as exc:
            return jsonrpc_error(request_id, -32602, str(exc))
        except LookupError as exc:
            return jsonrpc_error(request_id, -32602, str(exc))
        except MCPGatewayUpstreamError as exc:
            return jsonrpc_error(request_id, -32000, str(exc))

    return jsonrpc_error(request_id, -32601, f"Method not found: {method}")


@router.post("", operation_id="mcp_gateway_rpc")
async def mcp_gateway_rpc(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    organization_id_query: Annotated[UUID | None, Query(alias="organization_id")] = None,
    workspace_id_query: Annotated[UUID | None, Query(alias="workspace_id")] = None,
    organization_id_header: Annotated[
        UUID | None,
        Header(alias="X-Wardn-Organization-Id"),
    ] = None,
    workspace_id_header: Annotated[
        UUID | None,
        Header(alias="X-Wardn-Workspace-Id"),
    ] = None,
) -> Response:
    try:
        organization_id = choose_scope_id(
            organization_id_query,
            organization_id_header,
            name="organization_id",
        )
        workspace_id = choose_scope_id(
            workspace_id_query,
            workspace_id_header,
            name="workspace_id",
        )
        scope = await build_common_gateway_scope(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
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
