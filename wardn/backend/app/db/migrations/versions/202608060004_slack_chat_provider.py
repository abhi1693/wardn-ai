"""Add Slack chat provider.

Revision ID: 202608060004
Revises: 202608060003
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608060004"
down_revision: str | None = "202608060003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_chat_provider_connections_provider",
        "chat_provider_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_chat_provider_connections_provider",
        "chat_provider_connections",
        "provider IN ('telegram', 'whatsapp_local', 'slack')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_chat_provider_connections_provider",
        "chat_provider_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_chat_provider_connections_provider",
        "chat_provider_connections",
        "provider IN ('telegram', 'whatsapp_local')",
    )
