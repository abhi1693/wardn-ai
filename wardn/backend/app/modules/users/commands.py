import asyncio
import getpass
import sys
from types import SimpleNamespace
from typing import Annotated

import typer
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.cli_utils import exit_with_code
from app.db.session import AsyncSessionLocal
from app.modules.users.exceptions import DuplicateUserError
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user


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


async def create_superuser_from_args(args: SimpleNamespace) -> None:
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


def handle_createsuperuser(args: SimpleNamespace) -> int:
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


def createsuperuser_command(
    email: Annotated[str | None, typer.Option(help="Email address for the superuser.")] = None,
    first_name: Annotated[str, typer.Option(help="First name for the superuser.")] = "",
    last_name: Annotated[str, typer.Option(help="Last name for the superuser.")] = "",
    password: Annotated[
        str | None,
        typer.Option(help="Password for non-interactive use. Prefer interactive entry locally."),
    ] = None,
    no_input: Annotated[
        bool,
        typer.Option("--no-input", help="Do not prompt. Requires --email and --password."),
    ] = False,
) -> None:
    exit_with_code(
        handle_createsuperuser(
            SimpleNamespace(
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
                no_input=no_input,
            )
        )
    )


def register_user_commands(app: typer.Typer) -> None:
    app.command(
        "createsuperuser",
        help="Create a local superuser account.",
    )(createsuperuser_command)
