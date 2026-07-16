import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
from app.db.session import defer_session_work
from app.modules.limits import service as limits_service
from app.modules.organizations.service import require_organization_admin, require_workspace_admin
from app.modules.secrets import repository
from app.modules.secrets.exceptions import (
    DuplicateSecretHandleError,
    DuplicateSecretStoreError,
    InvalidSecretHandleError,
    InvalidSecretStoreError,
    SecretHandleNotFoundError,
    SecretInUseError,
    SecretStoreNotFoundError,
)
from app.modules.secrets.managed import (
    persist_managed_secret_intent,
    queue_managed_secret_cleanup_independently,
    reconcile_managed_secret_after_request,
)
from app.modules.secrets.models import ManagedSecret, SecretHandle, SecretStore
from app.modules.secrets.provider import ResolvedSecret, SecretResolutionContext, SecretWriteResult
from app.modules.secrets.providers.registry import get_secret_provider, supported_secret_providers
from app.modules.secrets.schemas import (
    SecretHandleCreate,
    SecretHandleListResponse,
    SecretHandleRead,
    SecretHandleUpdate,
    SecretStoreCreate,
    SecretStoreListResponse,
    SecretStoreRead,
    SecretStoreUpdate,
    SecretValidationResponse,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)

SECRET_HANDLE_IN_USE_CONSTRAINTS = frozenset(
    {
        "fk_llm_provider_credentials_api_key_secret_handle",
        "fk_llm_provider_credentials_oauth_access_secret_handle",
        "fk_llm_provider_credentials_oauth_refresh_secret_handle",
        "fk_managed_secrets_store",
    }
)


async def flush_secret_deletion(
    session: AsyncSession,
    *,
    in_use_message: str,
) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(exc, SECRET_HANDLE_IN_USE_CONSTRAINTS):
            raise SecretInUseError(in_use_message) from exc
        raise


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_external_ref(value: str) -> str:
    return value.strip().strip("/")


def normalize_provider(value: str) -> str:
    return value.strip().casefold()


def normalize_secret_store_url(config: dict) -> str:
    value = config.get("baseUrl") or config.get("base_url") or ""
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/").casefold()


async def require_secret_scope_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> None:
    if workspace_id is None:
        await require_organization_admin(session, user, organization_id)
    else:
        await require_workspace_admin(session, user, organization_id, workspace_id)


def store_response(store: SecretStore) -> SecretStoreRead:
    return SecretStoreRead(
        id=store.id,
        organizationId=store.organization_id,
        workspaceId=store.workspace_id,
        createdById=store.created_by_id,
        provider=store.provider,
        name=store.name,
        config=store.config,
        authConfig=store.auth_config,
        isActive=store.is_active,
        createdAt=store.created_at,
        updatedAt=store.updated_at,
    )


def handle_response(handle: SecretHandle) -> SecretHandleRead:
    return SecretHandleRead(
        id=handle.id,
        organizationId=handle.organization_id,
        workspaceId=handle.workspace_id,
        storeId=handle.store_id,
        createdById=handle.created_by_id,
        purpose=handle.purpose,
        displayName=handle.display_name,
        externalRef=handle.external_ref,
        keyName=handle.key_name,
        version=handle.version,
        handleMetadata=handle.handle_metadata,
        createdAt=handle.created_at,
        updatedAt=handle.updated_at,
    )


async def validate_provider_store(store: SecretStore) -> None:
    provider = get_secret_provider(store.provider)
    result = await provider.validate_store(store)
    if not result.ok:
        raise InvalidSecretStoreError(result.message or "secret store configuration is invalid")


async def ensure_unique_store_url(
    session: AsyncSession,
    organization_id: uuid.UUID,
    provider: str,
    config: dict,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    base_url = normalize_secret_store_url(config)
    if not base_url:
        return
    stores = await repository.list_stores(session, organization_id=organization_id)
    for store in stores:
        if exclude_id is not None and store.id == exclude_id:
            continue
        if store.provider != provider:
            continue
        if normalize_secret_store_url(store.config) == base_url:
            raise DuplicateSecretStoreError("secret backend URL already exists")


async def list_secret_stores(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
) -> SecretStoreListResponse:
    await require_secret_scope_admin(session, user, organization_id, workspace_id)
    stores = await repository.list_stores(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return SecretStoreListResponse(stores=[store_response(store) for store in stores])


async def get_secret_store(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    store_id: uuid.UUID,
) -> SecretStoreRead:
    store = await repository.get_store(
        session,
        organization_id=organization_id,
        store_id=store_id,
    )
    if store is None:
        raise SecretStoreNotFoundError("secret store not found")
    await require_secret_scope_admin(session, user, organization_id, store.workspace_id)
    return store_response(store)


async def create_secret_store(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: SecretStoreCreate,
) -> SecretStoreRead:
    name = normalize_name(payload.name)
    provider = normalize_provider(payload.provider)
    config = payload.config.model_dump(by_alias=True)
    auth_config = payload.auth_config.model_dump(by_alias=True)
    if provider not in supported_secret_providers():
        raise InvalidSecretStoreError("unsupported secret store provider")
    await require_secret_scope_admin(session, user, organization_id, payload.workspace_id)
    if await repository.get_store_by_name(
        session,
        organization_id=organization_id,
        workspace_id=payload.workspace_id,
        name=name,
    ):
        raise DuplicateSecretStoreError("secret store name already exists")
    await ensure_unique_store_url(
        session,
        organization_id,
        provider,
        config,
    )
    quota_scopes = [
        limits_service.quota_scope(
            limits_service.SECRET_STORES_PER_ORGANIZATION,
            organization_id,
        )
    ]
    if payload.workspace_id is not None:
        quota_scopes.append(
            limits_service.quota_scope(
                limits_service.SECRET_STORES_PER_WORKSPACE,
                payload.workspace_id,
            )
        )
    await limits_service.lock_quota_capacity(session, quota_scopes)
    store_count = await repository.count_stores_for_organization(session, organization_id)
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.SECRET_STORES_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=store_count,
    )
    if payload.workspace_id is not None:
        workspace_store_count = await repository.count_stores_for_workspace(
            session,
            payload.workspace_id,
        )
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.SECRET_STORES_PER_WORKSPACE,
            scope_chain=[
                ("workspace", payload.workspace_id),
                ("organization", organization_id),
            ],
            current_count=workspace_store_count,
        )
    store = SecretStore(
        organization_id=organization_id,
        workspace_id=payload.workspace_id,
        created_by_id=user.id,
        provider=provider,
        name=name,
        config=config,
        auth_config=auth_config,
        is_active=True,
    )
    await validate_provider_store(store)
    session.add(store)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {
                "uq_secret_stores_org_workspace_name",
                "uq_secret_stores_org_name",
                "uq_secret_stores_org_provider_base_url",
            },
        ):
            raise DuplicateSecretStoreError("secret store already exists") from exc
        raise
    await session.refresh(store)
    return store_response(store)


async def update_secret_store(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    store_id: uuid.UUID,
    payload: SecretStoreUpdate,
) -> SecretStoreRead:
    store = await repository.get_store(
        session,
        organization_id=organization_id,
        store_id=store_id,
    )
    if store is None:
        raise SecretStoreNotFoundError("secret store not found")
    await require_secret_scope_admin(session, user, organization_id, store.workspace_id)
    if (
        payload.config is not None or payload.auth_config is not None
    ) and await repository.has_managed_secrets_for_store(session, store.id):
        raise SecretInUseError(
            "secret store configuration cannot change while managed secrets exist"
        )

    if payload.name is not None:
        name = normalize_name(payload.name)
        existing = await repository.get_store_by_name(
            session,
            organization_id=organization_id,
            workspace_id=store.workspace_id,
            name=name,
        )
        if existing is not None and existing.id != store.id:
            raise DuplicateSecretStoreError("secret store name already exists")
        store.name = name
    if payload.config is not None:
        config = payload.config.model_dump(by_alias=True)
        await ensure_unique_store_url(
            session,
            organization_id,
            store.provider,
            config,
            exclude_id=store.id,
        )
        store.config = config
    if payload.auth_config is not None:
        store.auth_config = payload.auth_config.model_dump(by_alias=True)
    if payload.is_active is not None:
        store.is_active = payload.is_active
    await validate_provider_store(store)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {
                "uq_secret_stores_org_workspace_name",
                "uq_secret_stores_org_name",
                "uq_secret_stores_org_provider_base_url",
            },
        ):
            raise DuplicateSecretStoreError("secret store already exists") from exc
        raise
    await session.refresh(store)
    return store_response(store)


async def delete_secret_store(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    store_id: uuid.UUID,
) -> None:
    store = await repository.get_store(
        session,
        organization_id=organization_id,
        store_id=store_id,
    )
    if store is None:
        raise SecretStoreNotFoundError("secret store not found")
    await require_secret_scope_admin(session, user, organization_id, store.workspace_id)
    await session.delete(store)
    await flush_secret_deletion(
        session,
        in_use_message="secret store contains a handle or managed secret that is still in use",
    )


async def validate_secret_store(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    store_id: uuid.UUID,
) -> SecretValidationResponse:
    store = await repository.get_store(
        session,
        organization_id=organization_id,
        store_id=store_id,
    )
    if store is None:
        raise SecretStoreNotFoundError("secret store not found")
    await require_secret_scope_admin(session, user, organization_id, store.workspace_id)
    provider = get_secret_provider(store.provider)
    validate_connection = getattr(provider, "validate_connection", None)
    if validate_connection is not None:
        result = await validate_connection(store)
    else:
        result = await provider.validate_store(store)
    return SecretValidationResponse(ok=result.ok, message=result.message)


async def validate_handle_store_scope(
    session: AsyncSession,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    store_id: uuid.UUID,
) -> SecretStore:
    store = await repository.get_store(
        session,
        organization_id=organization_id,
        store_id=store_id,
    )
    if store is None or not store.is_active:
        raise InvalidSecretHandleError("secret store is not available")
    if workspace_id is None and store.workspace_id is not None:
        raise InvalidSecretHandleError(
            "organization-scoped handles cannot use workspace-scoped stores"
        )
    if store.workspace_id is not None and store.workspace_id != workspace_id:
        raise InvalidSecretHandleError("secret handle and store workspaces must match")
    return store


async def list_secret_handles(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
) -> SecretHandleListResponse:
    await require_secret_scope_admin(session, user, organization_id, workspace_id)
    handles = await repository.list_handles(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return SecretHandleListResponse(handles=[handle_response(handle) for handle in handles])


async def get_secret_handle(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID,
) -> SecretHandleRead:
    handle = await repository.get_handle(
        session,
        organization_id=organization_id,
        handle_id=handle_id,
    )
    if handle is None:
        raise SecretHandleNotFoundError("secret handle not found")
    await require_secret_scope_admin(session, user, organization_id, handle.workspace_id)
    return handle_response(handle)


async def create_secret_handle(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: SecretHandleCreate,
    *,
    managed_secret_id: uuid.UUID | None = None,
) -> SecretHandleRead:
    display_name = normalize_name(payload.display_name)
    external_ref = normalize_external_ref(payload.external_ref)
    await require_secret_scope_admin(session, user, organization_id, payload.workspace_id)
    store = await validate_handle_store_scope(
        session,
        organization_id,
        payload.workspace_id,
        payload.store_id,
    )
    if await repository.get_handle_by_display_name(
        session,
        organization_id=organization_id,
        workspace_id=payload.workspace_id,
        display_name=display_name,
    ):
        raise DuplicateSecretHandleError("secret handle display name already exists")
    if managed_secret_id is not None:
        managed_secret = await session.get(ManagedSecret, managed_secret_id)
        if (
            managed_secret is None
            or managed_secret.status != "provisioning"
            or managed_secret.organization_id != organization_id
            or managed_secret.workspace_id != payload.workspace_id
            or managed_secret.store_id != store.id
            or managed_secret.external_ref != external_ref
        ):
            raise InvalidSecretHandleError("managed secret does not match this handle")
    quota_scopes = [
        limits_service.quota_scope(
            limits_service.SECRET_HANDLES_PER_ORGANIZATION,
            organization_id,
        )
    ]
    if payload.workspace_id is not None:
        quota_scopes.append(
            limits_service.quota_scope(
                limits_service.SECRET_HANDLES_PER_WORKSPACE,
                payload.workspace_id,
            )
        )
    await limits_service.lock_quota_capacity(session, quota_scopes)
    handle_count = await repository.count_handles_for_organization(session, organization_id)
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.SECRET_HANDLES_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=handle_count,
    )
    if payload.workspace_id is not None:
        workspace_handle_count = await repository.count_handles_for_workspace(
            session,
            payload.workspace_id,
        )
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.SECRET_HANDLES_PER_WORKSPACE,
            scope_chain=[
                ("workspace", payload.workspace_id),
                ("organization", organization_id),
            ],
            current_count=workspace_handle_count,
        )
    handle = SecretHandle(
        organization_id=organization_id,
        workspace_id=payload.workspace_id,
        store_id=store.id,
        managed_secret_id=managed_secret_id,
        created_by_id=user.id,
        purpose=payload.purpose,
        display_name=display_name,
        external_ref=external_ref,
        key_name=payload.key_name.strip(),
        version=payload.version.strip(),
        handle_metadata=payload.metadata,
    )
    session.add(handle)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {
                "uq_secret_handles_org_workspace_display_name",
                "uq_secret_handles_org_display_name",
            },
        ):
            raise DuplicateSecretHandleError(
                "secret handle display name already exists"
            ) from exc
        raise
    await session.refresh(handle)
    return handle_response(handle)


async def update_secret_handle(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID,
    payload: SecretHandleUpdate,
) -> SecretHandleRead:
    handle = await repository.get_handle(
        session,
        organization_id=organization_id,
        handle_id=handle_id,
    )
    if handle is None:
        raise SecretHandleNotFoundError("secret handle not found")
    await require_secret_scope_admin(session, user, organization_id, handle.workspace_id)
    store_id = payload.store_id if payload.store_id is not None else handle.store_id
    await validate_handle_store_scope(session, organization_id, handle.workspace_id, store_id)

    if payload.display_name is not None:
        display_name = normalize_name(payload.display_name)
        existing = await repository.get_handle_by_display_name(
            session,
            organization_id=organization_id,
            workspace_id=handle.workspace_id,
            display_name=display_name,
        )
        if existing is not None and existing.id != handle.id:
            raise DuplicateSecretHandleError("secret handle display name already exists")
        handle.display_name = display_name
    if payload.store_id is not None:
        handle.store_id = payload.store_id
    if payload.purpose is not None:
        handle.purpose = payload.purpose
    if payload.external_ref is not None:
        handle.external_ref = normalize_external_ref(payload.external_ref)
    if payload.key_name is not None:
        handle.key_name = payload.key_name.strip()
    if payload.version is not None:
        handle.version = payload.version.strip()
    if payload.metadata is not None:
        handle.handle_metadata = payload.metadata
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {
                "uq_secret_handles_org_workspace_display_name",
                "uq_secret_handles_org_display_name",
            },
        ):
            raise DuplicateSecretHandleError(
                "secret handle display name already exists"
            ) from exc
        raise
    await session.refresh(handle)
    return handle_response(handle)


async def delete_secret_handle(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID,
) -> None:
    handle = await repository.get_handle(
        session,
        organization_id=organization_id,
        handle_id=handle_id,
    )
    if handle is None:
        raise SecretHandleNotFoundError("secret handle not found")
    await require_secret_scope_admin(session, user, organization_id, handle.workspace_id)
    if handle.managed_secret_id is not None:
        raise SecretInUseError("managed secret handles must be deleted with their owner")
    await session.delete(handle)
    await flush_secret_deletion(
        session,
        in_use_message="secret handle is used by an LLM provider credential",
    )


async def validate_secret_handle(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID,
) -> SecretValidationResponse:
    handle = await repository.get_handle(
        session,
        organization_id=organization_id,
        handle_id=handle_id,
    )
    if handle is None:
        raise SecretHandleNotFoundError("secret handle not found")
    await require_secret_scope_admin(session, user, organization_id, handle.workspace_id)
    store = await validate_handle_store_scope(
        session,
        organization_id,
        handle.workspace_id,
        handle.store_id,
    )
    result = await get_secret_provider(store.provider).validate_handle(store, handle)
    return SecretValidationResponse(ok=result.ok, message=result.message)


async def resolve_secret(
    session: AsyncSession,
    organization_id: uuid.UUID,
    handle_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
) -> ResolvedSecret:
    handle = await repository.get_handle(
        session,
        organization_id=organization_id,
        handle_id=handle_id,
    )
    if handle is None:
        raise SecretHandleNotFoundError("secret handle not found")
    if workspace_id is not None and handle.workspace_id not in (None, workspace_id):
        raise InvalidSecretHandleError("secret handle is not available in this workspace")
    store = await validate_handle_store_scope(
        session,
        organization_id,
        handle.workspace_id,
        handle.store_id,
    )
    return await get_secret_provider(store.provider).resolve(
        store,
        handle,
        SecretResolutionContext(
            organization_id=str(organization_id),
            workspace_id=str(workspace_id or handle.workspace_id)
            if workspace_id or handle.workspace_id
            else None,
            purpose=handle.purpose,
        ),
    )


async def write_secret_values(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None,
    external_ref: str,
    values: dict[str, str],
    purpose: str = "other",
    owner_type: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> SecretWriteResult:
    await require_secret_scope_admin(session, user, organization_id, workspace_id)
    store = await validate_handle_store_scope(session, organization_id, workspace_id, store_id)
    normalized_ref = normalize_external_ref(external_ref)
    if not normalized_ref:
        raise InvalidSecretHandleError("externalRef is required")
    sanitized_values = {
        str(key).strip(): value
        for key, value in values.items()
        if str(key).strip() and isinstance(value, str)
    }
    if not sanitized_values:
        raise InvalidSecretHandleError("secret values are required")
    if (owner_type is None) != (owner_id is None):
        raise ValueError("owner_type and owner_id must be provided together")

    managed_secret_id = None
    if owner_type is not None and owner_id is not None:
        managed_secret_id = await persist_managed_secret_intent(
            organization_id=organization_id,
            workspace_id=workspace_id,
            store_id=store.id,
            created_by_id=user.id,
            owner_type=owner_type,
            owner_id=owner_id,
            purpose=purpose,
            external_ref=normalized_ref,
        )

        async def reconcile(deferred_session: AsyncSession) -> None:
            await reconcile_managed_secret_after_request(
                deferred_session,
                managed_secret_id,
            )

        defer_session_work(session, reconcile)

    try:
        result = await get_secret_provider(store.provider).write(
            store,
            normalized_ref,
            sanitized_values,
            SecretResolutionContext(
                organization_id=str(organization_id),
                workspace_id=str(workspace_id) if workspace_id else None,
                purpose=purpose,
            ),
        )
    except BaseException:
        if managed_secret_id is not None:
            try:
                await queue_managed_secret_cleanup_independently(managed_secret_id)
            except BaseException:
                logger.exception(
                    "Could not immediately queue cleanup for managed secret %s; "
                    "the stale-provisioning worker will retry it.",
                    managed_secret_id,
                )
        raise
    return SecretWriteResult(
        version=result.version,
        managed_secret_id=managed_secret_id,
    )
