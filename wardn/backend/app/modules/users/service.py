import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_api_token,
    hash_api_token,
    hash_password,
    verify_api_token,
    verify_password,
)
from app.modules.users import repository
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidLoginError,
    UserNotFoundError,
)
from app.modules.users.models import LocalAuthCredential, User, UserAPIToken
from app.modules.users.schemas import LoginRequest, UserAPITokenCreate, UserCreate


def normalize_email(email: str) -> str:
    return email.strip().casefold()


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

    token_prefix, token = generate_api_token()
    record = UserAPIToken(
        user_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        token_prefix=token_prefix,
        token_hash=hash_api_token(token),
        is_active=True,
        expires_at=payload.expires_at,
    )
    session.add(record)
    await session.flush()
    return record, token


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
