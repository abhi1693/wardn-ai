import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.schemas import APIModel

GuardrailPolicyMode = Literal["allow", "deny", "require_confirmation"]


class GuardrailPolicyCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    mode: GuardrailPolicyMode
    priority: int = Field(default=100, ge=0)
    conditions: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @model_validator(mode="after")
    def normalize_strings(self) -> "GuardrailPolicyCreate":
        self.name = " ".join(self.name.strip().split())
        self.description = self.description.strip()
        return self


class GuardrailPolicyUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    mode: GuardrailPolicyMode | None = None
    priority: int | None = Field(default=None, ge=0)
    conditions: dict[str, Any] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize_strings(self) -> "GuardrailPolicyUpdate":
        if self.name is not None:
            self.name = " ".join(self.name.strip().split())
        if self.description is not None:
            self.description = self.description.strip()
        return self


class GuardrailPolicyRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    created_by_id: uuid.UUID | None = None
    name: str
    description: str
    mode: str
    priority: int
    conditions: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GuardrailPolicyListResponse(APIModel):
    policies: list[GuardrailPolicyRead]


class GuardrailDecisionRead(APIModel):
    mode: str
    policy_id: uuid.UUID | None = None
    policy_name: str = ""
    message: str = ""
    matched_policy_ids: list[uuid.UUID] = Field(default_factory=list)
