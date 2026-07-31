"""Repair file-backed MCP runtime secret references.

Revision ID: 202607310001
Revises: 202607300001
Create Date: 2026-07-31 00:01:00.000000
"""

from copy import deepcopy
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607310001"
down_revision: str | None = "202607300001"
branch_labels: str | None = None
depends_on: str | None = None


installations = sa.table(
    "mcp_server_installations",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("secret_references", postgresql.JSONB(astext_type=sa.Text())),
)


def _is_secret_handle_ref(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") == "secret_handle"


def _file_runtime_path(detail: Any) -> str:
    if not isinstance(detail, dict):
        return ""
    return str(detail.get("path") or detail.get("mountPath") or "").strip()


def _repair_secret_references(secret_references: Any) -> dict[str, Any] | None:
    if not isinstance(secret_references, dict):
        return None
    files = secret_references.get("files")
    if not isinstance(files, dict):
        return None

    file_paths = {
        str(key): path
        for key, detail in files.items()
        if (path := _file_runtime_path(detail))
    }
    if not file_paths:
        return None

    repaired = deepcopy(secret_references)
    changed = False
    for namespace in ("environment", "packageArguments"):
        namespace_values = repaired.get(namespace)
        if not isinstance(namespace_values, dict):
            continue
        for key, value in list(namespace_values.items()):
            path = file_paths.get(str(key))
            if path and _is_secret_handle_ref(value):
                namespace_values[key] = path
                changed = True

    return repaired if changed else None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(installations.c.id, installations.c.secret_references).where(
            installations.c.secret_references.has_key("files")  # noqa: W601
        )
    )
    for row in rows:
        repaired = _repair_secret_references(row.secret_references)
        if repaired is None:
            continue
        bind.execute(
            installations.update()
            .where(installations.c.id == row.id)
            .values(secret_references=repaired)
        )


def downgrade() -> None:
    pass
