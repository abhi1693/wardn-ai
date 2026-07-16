from enum import StrEnum


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentScope(StrEnum):
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"


class ConversationRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMProviderVisibility(StrEnum):
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    USER = "user"


class LLMProviderAuthMethod(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"


class MCPServerStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DELETED = "deleted"


class MCPCatalogSourceProvider(StrEnum):
    WARDN_HUB = "wardn_hub"
    OFFICIAL = "official"
    PULSEMCP = "pulsemcp"
    CUSTOM = "custom"


class MCPCatalogSyncMode(StrEnum):
    LATEST_ONLY = "latest_only"
    ALL_VERSIONS = "all_versions"


class MCPInstallationStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class MCPOperationJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MCPOperationCleanupStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
