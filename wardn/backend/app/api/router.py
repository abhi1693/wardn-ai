from fastapi import APIRouter

from app.modules.agents.router import workspace_router as workspace_agents_router
from app.modules.agents.router import workspace_runs_router as workspace_agent_runs_router
from app.modules.guardrails.router import workspace_router as workspace_guardrails_router
from app.modules.health.router import router as health_router
from app.modules.limits.router import router as limits_router
from app.modules.llm_providers.router import router as llm_provider_credentials_router
from app.modules.mcp_gateway.oauth import oauth_router as mcp_gateway_oauth_router
from app.modules.mcp_gateway.router import router as mcp_gateway_router
from app.modules.mcp_gateway.router import workspace_router as workspace_mcp_gateway_router
from app.modules.mcp_registry.router import organization_catalog_router
from app.modules.mcp_registry.router import organization_router as organization_mcp_registry_router
from app.modules.mcp_registry.router import workspace_router as workspace_mcp_registry_router
from app.modules.mcp_runtime.router import workspace_router as workspace_mcp_runtime_router
from app.modules.organizations.router import router as organizations_router
from app.modules.secrets.router import router as secrets_router
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(secrets_router)
api_router.include_router(limits_router)
api_router.include_router(llm_provider_credentials_router)
api_router.include_router(workspace_guardrails_router)
api_router.include_router(workspace_agents_router)
api_router.include_router(workspace_agent_runs_router)
api_router.include_router(organization_catalog_router)
api_router.include_router(organization_mcp_registry_router)
api_router.include_router(workspace_mcp_registry_router)
api_router.include_router(mcp_gateway_oauth_router)
api_router.include_router(mcp_gateway_router)
api_router.include_router(workspace_mcp_gateway_router)
api_router.include_router(workspace_mcp_runtime_router)
