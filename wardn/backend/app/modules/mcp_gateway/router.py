from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.mcp_gateway import service
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import require_workspace_admin
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


async def handle_mcp_gateway_rpc(
    request: Request,
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
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
                    workspace_id=workspace_id,
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
) -> Response:
    return await handle_mcp_gateway_rpc(request, session)


@workspace_router.post("", operation_id="workspace_mcp_gateway_rpc")
async def workspace_mcp_gateway_rpc(
    organization_id: UUID,
    workspace_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        await require_workspace_admin(session, current_user, organization_id, workspace_id)
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        return jsonrpc_error(None, -32602, str(exc))
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        return jsonrpc_error(None, -32603, str(exc))
    return await handle_mcp_gateway_rpc(request, session, workspace_id=workspace_id)
