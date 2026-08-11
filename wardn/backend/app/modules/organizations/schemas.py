from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, SecretStr

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
    guardrail_default_deny: bool | None = None


class WorkspaceRead(APIModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str
    status: str
    guardrail_default_deny: bool
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


class MemberRead(APIModel):
    membership_id: UUID | None
    user_id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    display_name: str
    role: str
    access_source: Literal["organization", "workspace"]
    organization_role: str | None = None
    created_at: datetime


class MemberListResponse(APIModel):
    members: list[MemberRead]
    current_user_id: UUID
    can_manage: bool
    can_manage_owners: bool


class MembershipRoleUpdate(APIModel):
    role: OrganizationRole


class InvitationCreate(APIModel):
    email: EmailStr
    role: OrganizationRole


InvitationScopeType = Literal["organization", "workspace"]
InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]


class InvitationRead(APIModel):
    id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    scope_type: InvitationScopeType
    email: EmailStr
    role: str
    status: InvitationStatus
    expires_at: datetime
    invited_by_id: UUID | None
    accepted_by_id: UUID | None
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvitationListResponse(APIModel):
    invitations: list[InvitationRead]


class PendingInvitationRead(APIModel):
    id: UUID
    role: str
    scope_type: InvitationScopeType
    organization_id: UUID
    organization_name: str
    workspace_id: UUID | None
    workspace_name: str | None
    expires_at: datetime


class PendingInvitationListResponse(APIModel):
    invitations: list[PendingInvitationRead]


class InvitationCreated(APIModel):
    invitation: InvitationRead
    token: str


class InvitationPreview(APIModel):
    email: EmailStr
    role: str
    scope_type: InvitationScopeType
    organization_id: UUID
    organization_name: str
    workspace_id: UUID | None
    workspace_name: str | None
    expires_at: datetime
    auth_mode: Literal["local", "oidc"]
    oidc_provider_name: str
    current_user_email: EmailStr | None = None


class InvitationRegistration(APIModel):
    password: SecretStr = Field(min_length=8)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)


class InvitationAcceptanceRead(APIModel):
    organization_id: UUID
    organization_name: str
    workspace_id: UUID | None
    workspace_name: str | None
    user_id: UUID
