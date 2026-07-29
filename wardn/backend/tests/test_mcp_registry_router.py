import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from app.modules.mcp_registry import router
from app.modules.mcp_runtime.providers.kubernetes import KubernetesReconcileError


@pytest.mark.asyncio
async def test_list_installed_server_tools_handles_kubernetes_runtime_errors(monkeypatch) -> None:
    async def require_workspace_member_or_404(*args, **kwargs):
        return None

    async def list_installation_tools(*args, **kwargs):
        raise KubernetesReconcileError("Kubernetes namespace reconcile failed")

    monkeypatch.setattr(router, "require_workspace_member_or_404", require_workspace_member_or_404)
    monkeypatch.setattr(router, "list_installation_tools", list_installation_tools)

    with pytest.raises(HTTPException) as exc_info:
        await router.list_workspace_installed_mcp_server_tools(
            organization_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            installation_id=uuid.uuid4(),
            session=SimpleNamespace(),
            current_user=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "installed MCP server could not list tools" in str(exc_info.value.detail)
