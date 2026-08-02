"""Typer command application for backend management tasks."""

import typer


def register_commands(app: typer.Typer) -> None:
    from app.modules.llm_providers.commands import register_llm_provider_commands
    from app.modules.mcp_registry.commands import register_mcp_registry_commands
    from app.modules.mcp_registry.job_commands import register_mcp_job_commands
    from app.modules.mcp_runtime.commands import register_mcp_runtime_commands
    from app.modules.secrets.commands import register_secret_commands
    from app.modules.users.commands import register_user_commands

    register_llm_provider_commands(app)
    register_mcp_registry_commands(app)
    register_mcp_job_commands(app)
    register_mcp_runtime_commands(app)
    register_secret_commands(app)
    register_user_commands(app)


def create_app() -> typer.Typer:
    command_app = typer.Typer(
        add_completion=False,
        help="Wardn backend management commands.",
        no_args_is_help=True,
    )
    register_commands(command_app)
    return command_app


app = create_app()
