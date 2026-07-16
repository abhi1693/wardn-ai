from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import APIModel

OrganizationStatus = Literal["active", "suspended", "archived"]
OrganizationRole = Literal["owner", "admin", "member"]
WorkspaceStatus = Literal["active", "archived"]
WorkspaceRole = Literal["owner", "admin", "member"]


class OrganizationCreate(APIModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]*$")


class OrganizationUpdate(APIModel):
    name: str = Field(min_length=1, max_length=150)
    status: OrganizationStatus = "active"


class OrganizationRead(APIModel):
    id: UUID
    name: str
    slug: str
    status: str
    current_user_role: str
    created_at: datetime
    updated_at: datetime


class OrganizationListResponse(APIModel):
    organizations: list[OrganizationRead]


class OrganizationMembershipRead(APIModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(default="", max_length=2000)


class WorkspaceUpdate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    status: WorkspaceStatus = "active"


class WorkspaceRead(APIModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str
    status: str
    current_user_role: str
    created_at: datetime
    updated_at: datetime


class WorkspaceListResponse(APIModel):
    workspaces: list[WorkspaceRead]


class WorkspaceMembershipRead(APIModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
