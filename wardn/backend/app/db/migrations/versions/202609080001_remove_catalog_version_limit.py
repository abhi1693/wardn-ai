"""Remove retired catalog server-version limits.

Revision ID: 202609080001
Revises: 202609070002
"""

from alembic import op

revision = "202609080001"
down_revision = "202609070002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM resource_limits "
        "WHERE limit_key = 'mcp_server_versions.per_organization'"
    )


def downgrade() -> None:
    # Deleted operator values cannot be reconstructed. Older application versions
    # still supply their licensed/community default if downgraded.
    pass
