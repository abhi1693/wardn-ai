import sys

from app.commands import app


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, prog_name="wardn")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
