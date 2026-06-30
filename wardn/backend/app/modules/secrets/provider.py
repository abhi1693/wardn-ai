from dataclasses import dataclass
from typing import Protocol

from app.modules.secrets.models import SecretHandle, SecretStore


@dataclass(frozen=True)
class SecretResolutionContext:
    organization_id: str
    workspace_id: str | None = None
    purpose: str | None = None


@dataclass(frozen=True)
class ResolvedSecret:
    value: str
    content_type: str = "text/plain"
    version: str | None = None


@dataclass(frozen=True)
class SecretWriteResult:
    version: str | None = None


@dataclass(frozen=True)
class SecretValidationResult:
    ok: bool
    message: str = ""


class SecretStoreProvider(Protocol):
    name: str

    async def validate_store(self, store: SecretStore) -> SecretValidationResult:
        ...

    async def validate_handle(
        self,
        store: SecretStore,
        handle: SecretHandle,
    ) -> SecretValidationResult:
        ...

    async def resolve(
        self,
        store: SecretStore,
        handle: SecretHandle,
        context: SecretResolutionContext,
    ) -> ResolvedSecret:
        ...

    async def write(
        self,
        store: SecretStore,
        external_ref: str,
        values: dict[str, str],
        context: SecretResolutionContext,
    ) -> SecretWriteResult:
        ...
