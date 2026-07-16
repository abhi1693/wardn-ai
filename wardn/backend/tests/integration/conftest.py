import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL_ENV = "WARDN_TEST_DATABASE_URL"


def _database_url_with_driver(database_url: str, driver: str, database: str):
    return make_url(database_url).set(drivername=driver, database=database)


@pytest.fixture(scope="session")
def migrated_postgres_url() -> Iterator[str]:
    base_database_url = os.getenv(TEST_DATABASE_URL_ENV)
    if not base_database_url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is required for PostgreSQL integration tests")

    database_name = f"wardn_integration_{uuid.uuid4().hex}"
    admin_url = _database_url_with_driver(
        base_database_url,
        "postgresql+psycopg",
        "postgres",
    )
    target_url = _database_url_with_driver(
        base_database_url,
        "postgresql+asyncpg",
        database_name,
    )
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        migration_environment = os.environ.copy()
        migration_environment["WARDN_DATABASE_URL"] = target_url.render_as_string(
            hide_password=False
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=migration_environment,
            check=True,
        )
        yield target_url.render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()


@pytest_asyncio.fixture
async def postgres_engine(migrated_postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_postgres_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()
