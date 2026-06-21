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
    assert args.verbose is False


def test_handle_reapmcpruntimes_rejects_invalid_limit(capsys) -> None:
    result = commands.handle_reapmcpruntimes(
        argparse.Namespace(limit=0, verbose=False)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "--limit must be greater than 0" in captured.err
