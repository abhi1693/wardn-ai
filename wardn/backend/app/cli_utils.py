import typer


def exit_with_code(code: int) -> None:
    if code:
        raise typer.Exit(code=code)
