import argparse

from app.commands.registry import CommandRegistry
from app.modules.mcp_runtime import commands


def test_register_mcp_runtime_commands_adds_reaper_command() -> None:
    registry = CommandRegistry()
    commands.register_mcp_runtime_commands(registry)

    parser = registry.build_parser()
    args = parser.parse_args(["reapmcpruntimes", "--limit", "25"])

    assert args.command == "reapmcpruntimes"
    assert args.handler == commands.handle_reapmcpruntimes
    assert args.limit == 25
    assert args.event_retention_days is None
    assert args.invocation_retention_days is None
    assert args.verbose is False

    args = parser.parse_args(
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
    assert args.event_retention_days == 7
    assert args.invocation_retention_days == 30


def test_handle_reapmcpruntimes_rejects_invalid_limit(capsys) -> None:
    result = commands.handle_reapmcpruntimes(
        argparse.Namespace(limit=0, verbose=False)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--limit must be greater than 0" in captured.err


def test_handle_reapmcpruntimes_rejects_invalid_event_retention(capsys) -> None:
    result = commands.handle_reapmcpruntimes(
        argparse.Namespace(
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
        argparse.Namespace(
            limit=10,
            event_retention_days=None,
            invocation_retention_days=-1,
            verbose=False,
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--invocation-retention-days must be 0 or greater" in captured.err
