"""Add agent identity and personality fields.

Revision ID: 202608120001
Revises: 202608110001
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608120001"
down_revision: str | None = "202608110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("personality", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column("identity_name", sa.String(length=50), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column("identity_theme", sa.String(length=120), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column("identity_emoji", sa.String(length=32), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column("identity_avatar", sa.String(length=512), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column(
            "identity_avatar_url",
            sa.String(length=1024),
            server_default="",
            nullable=False,
        ),
    )
    for column in (
        "personality",
        "identity_name",
        "identity_theme",
        "identity_emoji",
        "identity_avatar",
        "identity_avatar_url",
    ):
        op.alter_column("agents", column, server_default=None)


def downgrade() -> None:
    op.drop_column("agents", "identity_avatar_url")
    op.drop_column("agents", "identity_avatar")
    op.drop_column("agents", "identity_emoji")
    op.drop_column("agents", "identity_theme")
    op.drop_column("agents", "identity_name")
    op.drop_column("agents", "personality")
