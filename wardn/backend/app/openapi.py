import argparse
import json
from pathlib import Path

from app.main import create_app


def export_openapi(output_path: Path) -> None:
    schema = create_app().openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.openapi")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path where the generated OpenAPI JSON should be written.",
    )
    args = parser.parse_args(argv)
    export_openapi(args.output)
    print(f"OpenAPI schema written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
