from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError
from typer.testing import CliRunner

from app.commands import create_app
from app.modules.users import commands


def make_args(**overrides) -> SimpleNamespace:
    values = {
        "email": "admin@example.com",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "password": "correct horse battery staple",
        "no_input": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_createsuperuser_cli_passes_typed_options(monkeypatch) -> None:
    captured = {}

    def handle(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(commands, "handle_createsuperuser", handle)
    result = CliRunner().invoke(
        create_app(),
        [
            "createsuperuser",
            "--email",
            "admin@example.com",
            "--password",
            "pass",
            "--no-input",
        ],
    )

    assert result.exit_code == 0
    assert captured["args"] == SimpleNamespace(
        email="admin@example.com",
        first_name="",
        last_name="",
        password="pass",
        no_input=True,
    )


def test_handle_createsuperuser_reports_missing_no_input_fields(capsys) -> None:
    result = commands.handle_createsuperuser(make_args(email=None))

    captured = capsys.readouterr()
    assert result == 1
    assert "--no-input requires: email" in captured.err


def test_handle_createsuperuser_runs_async_creator(monkeypatch, capsys) -> None:
    called_with = None

    async def fake_create_superuser_from_args(args):
        nonlocal called_with
        called_with = args

    monkeypatch.setattr(commands, "create_superuser_from_args", fake_create_superuser_from_args)
    args = make_args()

    result = commands.handle_createsuperuser(args)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert called_with == args


def test_handle_createsuperuser_reports_missing_migrations(monkeypatch, capsys) -> None:
    async def raise_missing_table(*args, **kwargs):
        raise SQLAlchemyError('relation "users" does not exist')

    monkeypatch.setattr(commands, "create_superuser_from_args", raise_missing_table)

    result = commands.handle_createsuperuser(make_args())

    captured = capsys.readouterr()
    assert result == 1
    assert "database is not migrated" in captured.err
    assert "alembic upgrade head" in captured.err


def test_prompt_password_rejects_mismatch(monkeypatch) -> None:
    values = iter(["first-password", "second-password"])
    monkeypatch.setattr(commands.getpass, "getpass", lambda prompt: next(values))

    with pytest.raises(ValueError, match="passwords do not match"):
        commands.prompt_password()
