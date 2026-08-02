from types import SimpleNamespace

from typer.testing import CliRunner

from app.commands import create_app
from app.modules.mcp_runtime import commands


def test_reapmcpruntimes_cli_passes_typed_options(monkeypatch) -> None:
    captured = []

    def handle(args):
        captured.append(args)
        return 0

    monkeypatch.setattr(commands, "handle_reapmcpruntimes", handle)
    runner = CliRunner()

    result = runner.invoke(create_app(), ["reapmcpruntimes", "--limit", "25"])

    assert result.exit_code == 0
    assert captured[-1] == SimpleNamespace(
        limit=25,
        event_retention_days=None,
        invocation_retention_days=None,
        verbose=False,
    )

    result = runner.invoke(
        create_app(),
        [
            "reapmcpruntimes",
            "--limit",
            "25",
            "--event-retention-days",
            "7",
            "--invocation-retention-days",
            "30",
        ]
    )
    assert result.exit_code == 0
    assert captured[-1].event_retention_days == 7
    assert captured[-1].invocation_retention_days == 30


def test_handle_reapmcpruntimes_rejects_invalid_limit(capsys) -> None:
    result = commands.handle_reapmcpruntimes(
        SimpleNamespace(limit=0, verbose=False)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--limit must be greater than 0" in captured.err


def test_handle_reapmcpruntimes_rejects_invalid_event_retention(capsys) -> None:
    result = commands.handle_reapmcpruntimes(
        SimpleNamespace(
            limit=10,
            event_retention_days=-1,
            invocation_retention_days=None,
            verbose=False,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--event-retention-days must be 0 or greater" in captured.err


def test_handle_reapmcpruntimes_rejects_invalid_invocation_retention(capsys) -> None:
    result = commands.handle_reapmcpruntimes(
        SimpleNamespace(
            limit=10,
            event_retention_days=None,
            invocation_retention_days=-1,
            verbose=False,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--invocation-retention-days must be 0 or greater" in captured.err
