from fastapi import APIRouter

from app.modules.agents.router import workspace_router as workspace_agents_router
from app.modules.agents.router import workspace_runs_router as workspace_agent_runs_router
from app.modules.agents.router import workspace_skills_router
from app.modules.chat_providers.router import webhook_router as chat_provider_webhook_router
from app.modules.chat_providers.router import workspace_router as workspace_chat_providers_router
from app.modules.guardrails.router import workspace_router as workspace_guardrails_router
from app.modules.guardrails.router import (
    workspace_settings_router as workspace_guardrail_settings_router,
)
from app.modules.health.router import router as health_router
from app.modules.licensing.router import router as licensing_router
from app.modules.limits.router import router as limits_router
from app.modules.llm_providers.router import providers_router as llm_providers_router
from app.modules.llm_providers.router import router as llm_provider_credentials_router
from app.modules.mcp_gateway.oauth import oauth_router as mcp_gateway_oauth_router
from app.modules.mcp_gateway.router import router as mcp_gateway_router
from app.modules.mcp_gateway.router import workspace_router as workspace_mcp_gateway_router
from app.modules.mcp_registry.router import organization_catalog_router
from app.modules.mcp_registry.router import organization_router as organization_mcp_registry_router
from app.modules.mcp_registry.router import workspace_router as workspace_mcp_registry_router
from app.modules.mcp_runtime.router import workspace_router as workspace_mcp_runtime_router
from app.modules.observability.router import (
    organization_router as organization_observability_router,
)
from app.modules.observability.router import usage_router
from app.modules.observability.router import (
    workspace_router as workspace_observability_router,
)
from app.modules.organizations.membership_router import (
    invitation_router as membership_invitation_router,
)
from app.modules.organizations.membership_router import (
    organization_router as organization_membership_router,
)
from app.modules.organizations.router import router as organizations_router
from app.modules.scheduled_tasks.router import workspace_router as workspace_scheduled_tasks_router
from app.modules.secrets.router import router as secrets_router
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(organization_membership_router)
api_router.include_router(membership_invitation_router)
api_router.include_router(secrets_router)
api_router.include_router(limits_router)
api_router.include_router(licensing_router)
api_router.include_router(llm_providers_router)
api_router.include_router(llm_provider_credentials_router)
api_router.include_router(workspace_guardrail_settings_router)
api_router.include_router(workspace_guardrails_router)
api_router.include_router(usage_router)
api_router.include_router(organization_observability_router)
api_router.include_router(workspace_observability_router)
api_router.include_router(workspace_agents_router)
api_router.include_router(workspace_agent_runs_router)
api_router.include_router(workspace_skills_router)
api_router.include_router(workspace_chat_providers_router)
api_router.include_router(workspace_scheduled_tasks_router)
api_router.include_router(chat_provider_webhook_router)
api_router.include_router(organization_catalog_router)
api_router.include_router(organization_mcp_registry_router)
api_router.include_router(workspace_mcp_registry_router)
api_router.include_router(mcp_gateway_oauth_router)
api_router.include_router(mcp_gateway_router)
api_router.include_router(workspace_mcp_gateway_router)
api_router.include_router(workspace_mcp_runtime_router)
