import argparse
from collections.abc import Callable

CommandHandler = Callable[[argparse.Namespace], int]
ParserConfigurer = Callable[[argparse.ArgumentParser], None]
CommandDefinition = tuple[str, ParserConfigurer, CommandHandler]


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandDefinition] = {}

    def register(
        self,
        name: str,
        help_text: str,
        configure_parser: ParserConfigurer,
        handler: CommandHandler,
    ) -> None:
        self._commands[name] = (help_text, configure_parser, handler)

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="wardn")
        subparsers = parser.add_subparsers(dest="command", required=True)

        for name, (help_text, configure_parser, handler) in sorted(self._commands.items()):
            subparser = subparsers.add_parser(name, help=help_text)
            configure_parser(subparser)
            subparser.set_defaults(handler=handler)

        return parser


registry = CommandRegistry()
