from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OrganizationStatus = Literal["active", "suspended", "archived"]
OrganizationRole = Literal["owner", "admin", "member"]
WorkspaceStatus = Literal["active", "archived"]
WorkspaceRole = Literal["owner", "admin", "member"]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]*$")


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    status: OrganizationStatus = "active"


class OrganizationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    slug: str
    status: str
    current_user_role: str = Field(alias="currentUserRole")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationRead]


class OrganizationMembershipRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    user_id: UUID = Field(alias="userId")
    role: str
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(default="", max_length=2000)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    status: WorkspaceStatus = "active"


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    name: str
    slug: str
    description: str
    status: str
    current_user_role: str = Field(alias="currentUserRole")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceRead]


class WorkspaceMembershipRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    workspace_id: UUID = Field(alias="workspaceId")
    user_id: UUID = Field(alias="userId")
    role: str
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
