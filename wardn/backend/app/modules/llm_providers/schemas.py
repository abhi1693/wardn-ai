import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

LLMProviderVisibility = Literal["organization", "workspace", "user"]
LLMProviderAuthMethod = Literal["api_key", "oauth"]
LLMProviderOAuthProvider = Literal["chatgpt"]


class LLMProviderCredentialCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=50)
    visibility: LLMProviderVisibility = "organization"
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    auth_method: LLMProviderAuthMethod = Field(default="api_key", alias="authMethod")
    api_key_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="apiKeySecretHandleId",
    )
    api_key_secret_store_id: uuid.UUID | None = Field(
        default=None,
        alias="apiKeySecretStoreId",
    )
    api_key: SecretStr | None = Field(default=None, alias="apiKey", min_length=1)
    oauth_provider: LLMProviderOAuthProvider | None = Field(default=None, alias="oauthProvider")
    oauth_access_token_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="oauthAccessTokenSecretHandleId",
    )
    oauth_refresh_token_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="oauthRefreshTokenSecretHandleId",
    )
    oauth_expires_at: datetime | None = Field(default=None, alias="oauthExpiresAt")
    oauth_scopes: list[str] = Field(default_factory=list, alias="oauthScopes")
    oauth_metadata: dict[str, Any] = Field(default_factory=dict, alias="oauthMetadata")
    base_url: str = Field(default="", alias="baseUrl", max_length=2048)
    extra_headers: dict[str, str] = Field(default_factory=dict, alias="extraHeaders")

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


class LLMProviderCredentialUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = Field(default=None, min_length=1, max_length=50)
    visibility: LLMProviderVisibility | None = None
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    auth_method: LLMProviderAuthMethod | None = Field(default=None, alias="authMethod")
    api_key_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="apiKeySecretHandleId",
    )
    oauth_provider: LLMProviderOAuthProvider | None = Field(default=None, alias="oauthProvider")
    oauth_access_token_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="oauthAccessTokenSecretHandleId",
    )
    oauth_refresh_token_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="oauthRefreshTokenSecretHandleId",
    )
    oauth_expires_at: datetime | None = Field(default=None, alias="oauthExpiresAt")
    oauth_scopes: list[str] | None = Field(default=None, alias="oauthScopes")
    oauth_metadata: dict[str, Any] | None = Field(default=None, alias="oauthMetadata")
    base_url: str | None = Field(default=None, alias="baseUrl", max_length=2048)
    extra_headers: dict[str, str] | None = Field(default=None, alias="extraHeaders")
    is_active: bool | None = Field(default=None, alias="isActive")


class LLMProviderCredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID = Field(alias="organizationId")
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    user_id: uuid.UUID | None = Field(default=None, alias="userId")
    name: str
    provider: str
    visibility: LLMProviderVisibility
    auth_method: LLMProviderAuthMethod = Field(alias="authMethod")
    api_key_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="apiKeySecretHandleId",
    )
    base_url: str = Field(alias="baseUrl")
    extra_headers: dict[str, str] = Field(alias="extraHeaders")
    oauth_provider: str = Field(alias="oauthProvider")
    oauth_access_token_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="oauthAccessTokenSecretHandleId",
    )
    oauth_refresh_token_secret_handle_id: uuid.UUID | None = Field(
        default=None,
        alias="oauthRefreshTokenSecretHandleId",
    )
    oauth_expires_at: datetime | None = Field(default=None, alias="oauthExpiresAt")
    oauth_scopes: list[str] = Field(alias="oauthScopes")
    oauth_metadata: dict[str, Any] = Field(alias="oauthMetadata")
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class LLMProviderCredentialListResponse(BaseModel):
    credentials: list[LLMProviderCredentialRead]


class LLMProviderModelRead(BaseModel):
    id: str
    name: str


class LLMProviderModelListResponse(BaseModel):
    models: list[LLMProviderModelRead]


class LLMProviderCredentialValidationResponse(BaseModel):
    ok: bool
    message: str = ""
