from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import authorization
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("require_http_scope", "service_name", "error", "expected_status"),
    (
        (
            authorization.require_organization_member_or_404,
            "require_organization_member",
            OrganizationNotFoundError("organization not found"),
            404,
        ),
        (
            authorization.require_organization_admin_or_404,
            "require_organization_admin",
            OrganizationAccessDeniedError("organization access denied"),
            403,
        ),
        (
            authorization.require_workspace_member_or_404,
            "require_workspace_member",
            WorkspaceNotFoundError("workspace not found"),
            404,
        ),
        (
            authorization.require_workspace_admin_or_404,
            "require_workspace_admin",
            WorkspaceAccessDeniedError("workspace access denied"),
            403,
        ),
    ),
)
async def test_scoped_authorization_translates_domain_errors(
    monkeypatch,
    require_http_scope,
    service_name,
    error,
    expected_status,
) -> None:
    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(authorization.organization_service, service_name, fail)
    arguments = [object(), object(), uuid4()]
    if "workspace" in service_name:
        arguments.append(uuid4())

    with pytest.raises(HTTPException) as caught:
        await require_http_scope(*arguments)

    assert caught.value.status_code == expected_status
    assert caught.value.detail == str(error)
