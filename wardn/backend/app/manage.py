import sys

from app.commands.registry import registry
from app.modules.mcp_registry.commands import register_mcp_registry_commands
from app.modules.mcp_runtime.commands import register_mcp_runtime_commands
from app.modules.users.commands import register_user_commands


def register_commands() -> None:
    register_mcp_registry_commands(registry)
    register_mcp_runtime_commands(registry)
    register_user_commands(registry)


def main(argv: list[str] | None = None) -> int:
    register_commands()
    parser = registry.build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
