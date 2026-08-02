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
    bridge_base_url: str = Field(default="", max_length=2048)
    bridge_user_id: str = Field(default="", max_length=255)
    outbound_webhook_url: str = Field(default="", max_length=2048)
    reply_on_unsupported_messages: bool = False
    allow_all_senders: bool = False
    allowed_sender_ids: list[str] = Field(default_factory=list)
    allowed_chat_ids: list[str] = Field(default_factory=list)

    @field_validator("account_name", "bridge_base_url", "bridge_user_id", "outbound_webhook_url")
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
    secret_store_id: uuid.UUID | None = None
    secret_values: dict[str, str] = Field(default_factory=dict)
    secret_handle_ids: dict[str, uuid.UUID] = Field(default_factory=dict)
    config: ProviderConfig = Field(default_factory=dict)

    @field_validator("name", "external_id", "display_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("secret_values")
    @classmethod
    def normalize_secret_values(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            str(key).strip().lower(): secret
            for key, secret in value.items()
            if str(key).strip() and isinstance(secret, str) and secret.strip()
        }


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


class ChatProviderPairingStatusResponse(APIModel):
    ok: bool
    provider: str
    status: Literal[
        "unsupported",
        "not_configured",
        "needs_pairing",
        "waiting_for_scan",
        "connected",
        "disconnected",
        "error",
    ]
    message: str = ""
    bridge_base_url: str = ""
    bridge_user_id: str = ""
    qr_payload: str = ""
    qr_expires_at: datetime | None = None
    phone_number: str = ""
    raw_status: dict[str, Any] = Field(default_factory=dict)


class ChatProviderWebhookResponse(APIModel):
    ok: bool = True
    received: int = 0
    processed: int = 0
    ignored: int = 0
    duplicates: int = 0
    failed: int = 0


class ChatProviderTestMessageRequest(APIModel):
    text: str = Field(min_length=1, max_length=4000)
    external_thread_id: str = Field(default="wardn-test", min_length=1, max_length=255)
    external_user_id: str = Field(default="", max_length=255)
    external_user_display_name: str = Field(default="Wardn test", max_length=255)

    @field_validator(
        "text",
        "external_thread_id",
        "external_user_id",
        "external_user_display_name",
    )
    @classmethod
    def normalize_message_text(cls, value: str) -> str:
        return " ".join(value.strip().split())


class ChatProviderTestMessageResponse(APIModel):
    ok: bool
    processed: bool
    event_id: str
    conversation_id: uuid.UUID | None = None
    thread_id: uuid.UUID | None = None
    reply_text: str = ""
    message: str = ""
