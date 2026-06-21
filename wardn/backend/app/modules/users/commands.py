import argparse
import asyncio
import getpass
import sys

from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.commands.registry import CommandRegistry
from app.db.session import AsyncSessionLocal
from app.modules.users.exceptions import DuplicateUserError
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user


def configure_createsuperuser_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--email", help="Email address for the superuser.")
    parser.add_argument("--first-name", default="", help="First name for the superuser.")
    parser.add_argument("--last-name", default="", help="Last name for the superuser.")
    parser.add_argument(
        "--password",
        help="Password for non-interactive use. Prefer interactive entry locally.",
    )
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="Do not prompt. Requires --email and --password.",
    )


def prompt_value(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default or ""


def prompt_password() -> str:
    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Password (again): ")
    if password != password_confirm:
        raise ValueError("passwords do not match")
    return password


async def create_superuser_from_args(args: argparse.Namespace) -> None:
    email = args.email
    first_name = args.first_name
    last_name = args.last_name
    password = args.password

    if args.no_input:
        missing = [
            name
            for name, value in (("email", email), ("password", password))
            if not value
        ]
        if missing:
            raise ValueError(f"--no-input requires: {', '.join(missing)}")
    else:
        email = email or prompt_value("Email")
        first_name = first_name or prompt_value("First name")
        last_name = last_name or prompt_value("Last name")
        password = password or prompt_password()

    payload = UserCreate(
        email=email,
        first_name=first_name,
        last_name=last_name,
        password=SecretStr(password),
    )

    async with AsyncSessionLocal() as session:
        user = await create_user(session, payload, is_superuser=True)
        await session.commit()
        await session.refresh(user)
        print(f"Superuser created: {user.email}")


def handle_createsuperuser(args: argparse.Namespace) -> int:
    try:
        asyncio.run(create_superuser_from_args(args))
    except (DuplicateUserError, ValidationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        if "relation \"users\" does not exist" in str(exc):
            print("Error: database is not migrated. Run `alembic upgrade head`.", file=sys.stderr)
        else:
            print(f"Database error: {exc}", file=sys.stderr)
        return 1
    return 0


def register_user_commands(registry: CommandRegistry) -> None:
    registry.register(
        "createsuperuser",
        "Create a local superuser account.",
        configure_createsuperuser_parser,
        handle_createsuperuser,
    )
