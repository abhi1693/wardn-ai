from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_catalog_limit_migration_removes_only_retired_overrides() -> None:
    migration = import_module(
        "app.db.migrations.versions.202609080001_remove_catalog_version_limit"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE resource_limits (limit_key TEXT, value INTEGER)"))
        connection.execute(
            text("INSERT INTO resource_limits (limit_key, value) VALUES (:key, :value)"),
            [
                {"key": "mcp_server_versions.per_organization", "value": 50},
                {"key": "mcp_server_versions.per_organization", "value": 1000},
                {"key": "mcp_server_installations.per_workspace", "value": 7},
                {"key": "mcp_catalog_sources.per_organization", "value": 2},
            ],
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()

        remaining = dict(
            connection.execute(text("SELECT limit_key, value FROM resource_limits")).all()
        )
        assert remaining == {
            "mcp_server_installations.per_workspace": 7,
            "mcp_catalog_sources.per_organization": 2,
        }
    engine.dispose()
