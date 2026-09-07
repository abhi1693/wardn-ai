"""Run only with WARDN_LOG_TEST_DATABASE_URL pointing to a disposable PostgreSQL DB."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.modules.observability import job_logs

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("WARDN_LOG_TEST_DATABASE_URL"),
        reason="requires disposable logging PostgreSQL",
    ),
]


def test_runtime_log_migration_storage_retention_concurrency_and_rollback(monkeypatch):
    url = os.environ["WARDN_LOG_TEST_DATABASE_URL"]
    settings = Settings(database_url=url, job_log_max_entries=100)
    monkeypatch.setattr(job_logs, "get_settings", lambda: settings)
    engine = create_engine(make_url(url).set(drivername="postgresql+psycopg"))
    migration = import_module("app.db.migrations.versions.202609080002_runtime_job_logs")
    first_org, other_org, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE organizations (id UUID PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE operation_probe (id INTEGER)"))
        connection.execute(
            text("INSERT INTO organizations VALUES (:first), (:other)"),
            {"first": first_org, "other": other_org},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    def record(organization_id, number):
        return {
            "organization_id": str(organization_id),
            "job_kind": "mcp_operation",
            "job_id": str(job_id),
            "entry": {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "message": f"event {number}",
                "fields": {"sequence": number},
            },
        }

    try:
        job_logs.write_records([record(first_org, index) for index in range(120)])
        job_logs.write_records([record(other_org, 0)])
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT entry->'fields'->>'sequence' FROM runtime_job_logs "
                        "WHERE organization_id=:org ORDER BY id"
                    ),
                    {"org": first_org},
                )
                .scalars()
                .all()
            )
            assert [int(value) for value in rows] == list(range(20, 120))
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM runtime_job_logs WHERE organization_id=:org"),
                    {"org": other_org},
                )
                == 1
            )
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM runtime_job_logs WHERE organization_id=:org"), {"org": first_org}
            )
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda index: job_logs.write_records([record(first_org, index)]), range(40)
                )
            )
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, entry->'fields'->>'sequence' FROM runtime_job_logs "
                    "WHERE organization_id=:org ORDER BY id"
                ),
                {"org": first_org},
            ).all()
            assert len(rows) == 40 and len({row[0] for row in rows}) == 40
            assert {int(row[1]) for row in rows} == set(range(40))
            transaction = connection.get_transaction()
            connection.execute(text("INSERT INTO operation_probe VALUES (1)"))
            job_logs.write_records([record(first_org, 1000)])
            transaction.rollback()
            assert connection.scalar(text("SELECT count(*) FROM operation_probe")) == 0
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM runtime_job_logs "
                        "WHERE entry->'fields'->>'sequence'='1000'"
                    )
                )
                == 1
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE runtime_job_logs SET expires_at=now()-interval '1 second' "
                    "WHERE organization_id=:org"
                ),
                {"org": first_org},
            )
        job_logs.write_records([])
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM runtime_job_logs")) == 1
    finally:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            connection.execute(text("DROP TABLE operation_probe, organizations"))
        engine.dispose()
