import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from app.core.schemas import APIModel

ChatProviderType = Literal["telegram", "whatsapp_local"]


class TelegramProviderConfig(APIModel):
    reply_on_unsupported_messages: bool = False
    allow_all_senders: bool = False
    allowed_sender_ids: list[str] = Field(default_factory=list)
    allowed_chat_ids: list[str] = Field(default_factory=list)

    @field_validator("allowed_sender_ids", "allowed_chat_ids")
    @classmethod
    def normalize_allowed_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})


class WhatsAppLocalProviderConfig(APIModel):
    account_name: str = Field(default="", max_length=100)
    outbound_webhook_url: str = Field(default="", max_length=2048)
    reply_on_unsupported_messages: bool = False
    allow_all_senders: bool = False
    allowed_sender_ids: list[str] = Field(default_factory=list)
    allowed_chat_ids: list[str] = Field(default_factory=list)

    @field_validator("account_name", "outbound_webhook_url")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("allowed_sender_ids", "allowed_chat_ids")
    @classmethod
    def normalize_allowed_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})


ProviderConfig = dict[str, Any]


class ChatProviderConnectionCreate(APIModel):
    provider: ChatProviderType
    name: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(default="", max_length=255)
    secret_handle_ids: dict[str, uuid.UUID] = Field(default_factory=dict)
    config: ProviderConfig = Field(default_factory=dict)

    @field_validator("name", "external_id", "display_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.strip().split())


class ChatProviderConnectionUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    secret_handle_ids: dict[str, uuid.UUID] | None = None
    config: ProviderConfig | None = None
    is_active: bool | None = None

    @field_validator("name", "external_id", "display_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.strip().split())


class ChatProviderConnectionRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    created_by_id: uuid.UUID | None = None
    provider: str
    name: str
    external_id: str
    display_name: str
    secret_handle_ids: dict[str, uuid.UUID] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ChatProviderConnectionListResponse(APIModel):
    connections: list[ChatProviderConnectionRead]


class ChatProviderWebhookResponse(APIModel):
    ok: bool = True
    received: int = 0
    processed: int = 0
    ignored: int = 0
    duplicates: int = 0
    failed: int = 0
