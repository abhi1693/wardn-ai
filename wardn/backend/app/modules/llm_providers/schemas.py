import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, SecretStr, model_validator

from app.core.schemas import APIModel

LLMProviderVisibility = Literal["organization", "workspace", "user"]
LLMProviderAuthMethod = Literal["api_key", "oauth"]
LLMProviderOAuthProvider = Literal["chatgpt"]


class LLMProviderCredentialCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=50)
    visibility: LLMProviderVisibility = "organization"
    workspace_id: uuid.UUID | None = None
    auth_method: LLMProviderAuthMethod = "api_key"
    api_key_secret_handle_id: uuid.UUID | None = None
    api_key_secret_store_id: uuid.UUID | None = None
    api_key: SecretStr | None = Field(default=None, min_length=1)
    oauth_provider: LLMProviderOAuthProvider | None = None
    oauth_access_token_secret_handle_id: uuid.UUID | None = None
    oauth_refresh_token_secret_handle_id: uuid.UUID | None = None
    oauth_expires_at: datetime | None = None
    oauth_scopes: list[str] = Field(default_factory=list)
    oauth_metadata: dict[str, Any] = Field(default_factory=dict)
    base_url: str = Field(default="", max_length=2048)
    extra_headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> "LLMProviderCredentialCreate":
        if self.visibility == "workspace" and self.workspace_id is None:
            raise ValueError("workspaceId is required for workspace-scoped credentials")
        if self.visibility != "workspace" and self.workspace_id is not None:
            raise ValueError("workspaceId is only valid for workspace-scoped credentials")
        if self.auth_method == "api_key":
            if self.api_key is None and self.api_key_secret_handle_id is None:
                raise ValueError(
                    "apiKey or apiKeySecretHandleId is required for api_key credentials"
                )
            if self.api_key is not None and self.api_key_secret_store_id is None:
                raise ValueError("apiKeySecretStoreId is required when apiKey is provided")
            if self.oauth_provider is not None:
                raise ValueError("oauthProvider is only valid for oauth credentials")
        if self.auth_method == "oauth":
            if self.api_key is not None or self.api_key_secret_store_id is not None:
                raise ValueError(
                    "apiKey and apiKeySecretStoreId are only valid for api_key credentials"
                )
            if self.oauth_provider is None:
                raise ValueError("oauthProvider is required for oauth credentials")
            if self.api_key_secret_handle_id is not None:
                raise ValueError("apiKeySecretHandleId is only valid for api_key credentials")
            if (
                self.oauth_access_token_secret_handle_id is None
                or self.oauth_refresh_token_secret_handle_id is None
            ):
                raise ValueError(
                    "oauthAccessTokenSecretHandleId and "
                    "oauthRefreshTokenSecretHandleId are required for oauth credentials"
                )
        return self


class LLMProviderCredentialUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = Field(default=None, min_length=1, max_length=50)
    visibility: LLMProviderVisibility | None = None
    workspace_id: uuid.UUID | None = None
    auth_method: LLMProviderAuthMethod | None = None
    api_key_secret_handle_id: uuid.UUID | None = None
    oauth_provider: LLMProviderOAuthProvider | None = None
    oauth_access_token_secret_handle_id: uuid.UUID | None = None
    oauth_refresh_token_secret_handle_id: uuid.UUID | None = None
    oauth_expires_at: datetime | None = None
    oauth_scopes: list[str] | None = None
    oauth_metadata: dict[str, Any] | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    extra_headers: dict[str, str] | None = None
    is_active: bool | None = None


class LLMProviderCredentialRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    name: str
    provider: str
    visibility: LLMProviderVisibility
    auth_method: LLMProviderAuthMethod
    api_key_secret_handle_id: uuid.UUID | None = None
    base_url: str
    extra_headers: dict[str, str]
    oauth_provider: str
    oauth_access_token_secret_handle_id: uuid.UUID | None = None
    oauth_refresh_token_secret_handle_id: uuid.UUID | None = None
    oauth_expires_at: datetime | None = None
    oauth_scopes: list[str]
    oauth_metadata: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LLMProviderCredentialListResponse(APIModel):
    credentials: list[LLMProviderCredentialRead]


class LLMProviderModelRead(APIModel):
    id: str
    name: str


class LLMProviderModelListResponse(APIModel):
    models: list[LLMProviderModelRead]


class LLMProviderCredentialValidationResponse(APIModel):
    ok: bool
    message: str = ""


class ChatGPTDeviceAuthorizationStartResponse(APIModel):
    device_auth_id: str
    user_code: str
    verification_url: str
    interval_seconds: int


class ChatGPTDeviceAuthorizationCompleteRequest(APIModel):
    device_auth_id: str = Field(min_length=1)
    user_code: str = Field(min_length=1)
    credential_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    secret_store_id: uuid.UUID | None = None
    visibility: LLMProviderVisibility = "organization"
    workspace_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "ChatGPTDeviceAuthorizationCompleteRequest":
        if self.credential_id is None:
            if self.name is None:
                raise ValueError("name is required when creating a ChatGPT credential")
            if self.secret_store_id is None:
                raise ValueError("secretStoreId is required when creating a ChatGPT credential")
            if self.visibility == "workspace" and self.workspace_id is None:
                raise ValueError("workspaceId is required for workspace-scoped credentials")
            if self.visibility != "workspace" and self.workspace_id is not None:
                raise ValueError("workspaceId is only valid for workspace-scoped credentials")
        return self


class ChatGPTDeviceAuthorizationCompleteResponse(APIModel):
    status: Literal["pending", "connected"]
    credential: LLMProviderCredentialRead | None = None
