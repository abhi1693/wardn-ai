import uuid

from app.core.config import Settings, get_settings


def agent_tool_approval_url(
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    settings: Settings | None = None,
) -> str:
    resolved_settings = settings or get_settings()
    base_url = resolved_settings.frontend_base_url.rstrip("/")
    return (
        f"{base_url}/org/{organization_id}/workspace/{workspace_id}"
        f"/agents/{agent_id}/approvals/{approval_id}"
    )
