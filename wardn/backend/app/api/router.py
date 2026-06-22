from fastapi import APIRouter

from app.modules.health.router import router as health_router
from app.modules.mcp_gateway.router import router as mcp_gateway_router
from app.modules.mcp_gateway.router import workspace_router as workspace_mcp_gateway_router
from app.modules.mcp_registry.router import organization_router as organization_mcp_registry_router
from app.modules.mcp_registry.router import router as mcp_registry_router
from app.modules.mcp_registry.router import workspace_router as workspace_mcp_registry_router
from app.modules.organizations.router import router as organizations_router
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(organization_mcp_registry_router)
api_router.include_router(workspace_mcp_registry_router)
api_router.include_router(workspace_mcp_gateway_router)
api_router.include_router(mcp_registry_router)
api_router.include_router(mcp_gateway_router)
