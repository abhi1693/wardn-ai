import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GuardrailPolicyMode = Literal["allow", "deny", "require_confirmation"]


class GuardrailPolicyCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    mode: GuardrailPolicyMode
    priority: int = Field(default=100, ge=0)
    conditions: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = Field(default=True, alias="isActive")

    @model_validator(mode="after")
    def normalize_strings(self) -> "GuardrailPolicyCreate":
        self.name = " ".join(self.name.strip().split())
        self.description = self.description.strip()
        return self


class GuardrailPolicyUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    mode: GuardrailPolicyMode | None = None
    priority: int | None = Field(default=None, ge=0)
    conditions: dict[str, Any] | None = None
    is_active: bool | None = Field(default=None, alias="isActive")

    @model_validator(mode="after")
    def normalize_strings(self) -> "GuardrailPolicyUpdate":
        if self.name is not None:
            self.name = " ".join(self.name.strip().split())
        if self.description is not None:
            self.description = self.description.strip()
        return self


class GuardrailPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID = Field(alias="organizationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    created_by_id: uuid.UUID | None = Field(default=None, alias="createdById")
    name: str
    description: str
    mode: str
    priority: int
    conditions: dict[str, Any]
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class GuardrailPolicyListResponse(BaseModel):
    policies: list[GuardrailPolicyRead]


class GuardrailDecisionRead(BaseModel):
    mode: str
    policy_id: uuid.UUID | None = Field(default=None, alias="policyId")
    policy_name: str = Field(default="", alias="policyName")
    message: str = ""
    matched_policy_ids: list[uuid.UUID] = Field(default_factory=list, alias="matchedPolicyIds")
