import logging

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.logging import configure_logging, log_context
from app.db.base import Base, import_models

config = context.config

configure_logging("migration")
logger = logging.getLogger("app.db.migrations")

import_models()
target_metadata = Base.metadata


def get_database_url() -> str:
    return get_settings().database_url.get_secret_value().replace("+asyncpg", "+psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


with log_context(service="migration"):
    logger.info("migration_started")
    try:
        if context.is_offline_mode():
            run_migrations_offline()
        else:
            run_migrations_online()
    except Exception:
        logger.exception("migration_failed")
        # Alembic's CLI otherwise prints the raw exception (including SQL/parameters)
        # after our sanitized diagnostic has already been emitted.
        raise SystemExit(1) from None
    else:
        logger.info("migration_completed")
