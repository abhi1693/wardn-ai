import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    extract_api_token_key,
    generate_api_token,
    hash_api_token,
    hash_password,
    verify_api_token,
    verify_password,
)
from app.modules.organizations import repository as organizations_repository
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import require_organization_admin, require_workspace_member
from app.modules.users import repository
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidAPITokenScopeError,
    InvalidLoginError,
    UserAPITokenNotFoundError,
    UserNotFoundError,
)
from app.modules.users.models import LocalAuthCredential, User, UserAPIToken
from app.modules.users.schemas import (
    LoginRequest,
    UserAPITokenCreate,
    UserAPITokenUpdate,
    UserCreate,
)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def unique_uuid_strings(values: list[uuid.UUID]) -> list[str]:
    return sorted({str(value) for value in values})


async def validate_api_token_scope(
    session: AsyncSession,
    user: User,
    *,
    organization_ids: list[uuid.UUID],
    workspace_ids: list[uuid.UUID],
) -> tuple[list[str], list[str]]:
    for organization_id in organization_ids:
        try:
            await require_organization_admin(session, user, organization_id)
        except (OrganizationNotFoundError, OrganizationAccessDeniedError) as exc:
            raise InvalidAPITokenScopeError(
                f"API token cannot be scoped to organization {organization_id}"
            ) from exc
    for workspace_id in workspace_ids:
        workspace = await organizations_repository.get_workspace_by_id(session, workspace_id)
        if workspace is None:
            raise InvalidAPITokenScopeError(
                f"API token cannot be scoped to workspace {workspace_id}"
            )
        try:
            await require_workspace_member(
                session,
                user,
                workspace.organization_id,
                workspace_id,
            )
        except (
            OrganizationNotFoundError,
            OrganizationAccessDeniedError,
            WorkspaceNotFoundError,
            WorkspaceAccessDeniedError,
        ) as exc:
            raise InvalidAPITokenScopeError(
                f"API token cannot be scoped to workspace {workspace_id}"
            ) from exc

    return unique_uuid_strings(organization_ids), unique_uuid_strings(workspace_ids)


async def create_user(
    session: AsyncSession,
    payload: UserCreate,
    *,
    is_superuser: bool = False,
) -> User:
    email = normalize_email(str(payload.email))

    if await repository.get_user_by_email(session, email):
        raise DuplicateUserError("email already exists")

    user = User(
        email=email,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        is_active=True,
        is_superuser=is_superuser,
    )
    user.local_credentials = LocalAuthCredential(
        password_hash=hash_password(payload.password.get_secret_value()),
        password_updated_at=datetime.now(UTC),
    )

    session.add(user)
    await session.flush()
    return user


async def bootstrap_superuser(session: AsyncSession, payload: UserCreate) -> User:
    if await repository.count_users(session) > 0:
        raise BootstrapUserExistsError("bootstrap user already exists")
    user = await create_user(session, payload, is_superuser=True)
    await session.commit()
    await session.refresh(user)
    return user


async def create_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: UserAPITokenCreate,
) -> tuple[UserAPIToken, str]:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError("user not found")

    organization_ids, workspace_ids = await validate_api_token_scope(
        session,
        user,
        organization_ids=payload.organization_ids,
        workspace_ids=payload.workspace_ids,
    )

    token_prefix, token = generate_api_token()
    record = UserAPIToken(
        user_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        token_prefix=token_prefix,
        token_hash=hash_api_token(token),
        organization_ids=organization_ids,
        workspace_ids=workspace_ids,
        is_active=True,
        expires_at=payload.expires_at,
    )
    session.add(record)
    await session.flush()
    return record, token


async def list_user_api_tokens(session: AsyncSession, user_id: uuid.UUID) -> list[UserAPIToken]:
    return await repository.list_user_api_tokens(session, user_id)


async def update_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
    payload: UserAPITokenUpdate,
) -> UserAPIToken:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError("user not found")

    token = await repository.get_user_api_token_by_id(session, user_id, token_id)
    if token is None:
        raise UserAPITokenNotFoundError("API token not found")

    if payload.name is not None:
        token.name = payload.name.strip()
    if payload.description is not None:
        token.description = payload.description.strip()
    if "expires_at" in payload.model_fields_set:
        token.expires_at = payload.expires_at
    if payload.is_active is not None:
        token.is_active = payload.is_active

    update_organizations = payload.organization_ids is not None
    update_workspaces = payload.workspace_ids is not None
    if update_organizations or update_workspaces:
        organization_ids, workspace_ids = await validate_api_token_scope(
            session,
            user,
            organization_ids=payload.organization_ids or [],
            workspace_ids=payload.workspace_ids or [],
        )
        if update_organizations:
            token.organization_ids = organization_ids
        if update_workspaces:
            token.workspace_ids = workspace_ids

    await session.flush()
    return token


async def delete_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
) -> None:
    deleted = await repository.delete_user_api_token(session, user_id, token_id)
    if not deleted:
        raise UserAPITokenNotFoundError("API token not found")


async def authenticate_local_user(session: AsyncSession, payload: LoginRequest) -> User:
    user = await repository.get_user_by_email(session, normalize_email(str(payload.email)))
    if user is None or user.local_credentials is None or not user.is_active:
        raise InvalidLoginError("invalid email or password")

    valid_password = verify_password(
        payload.password.get_secret_value(),
        user.local_credentials.password_hash,
    )
    if not valid_password:
        raise InvalidLoginError("invalid email or password")

    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user


def is_token_expired(token: UserAPIToken, *, now: datetime | None = None) -> bool:
    if token.expires_at is None:
        return False
    return token.expires_at <= (now or datetime.now(UTC))


def is_token_active(token: UserAPIToken, plaintext_token: str) -> bool:
    return token.is_active and not is_token_expired(token) and verify_api_token(
        plaintext_token,
        token.token_hash,
    )


async def authenticate_api_token(
    session: AsyncSession,
    plaintext_token: str,
) -> tuple[User, UserAPIToken] | None:
    token_prefix = extract_api_token_key(plaintext_token)
    if not token_prefix:
        return None
    api_token = await repository.get_api_token_by_prefix(session, token_prefix)
    if api_token is None or not is_token_active(api_token, plaintext_token):
        return None

    user = await repository.get_user_by_id(session, api_token.user_id)
    if user is None or not user.is_active:
        return None

    api_token.last_used_at = datetime.now(UTC)
    await session.flush()
    return user, api_token
