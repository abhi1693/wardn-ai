"""Add workspace skill library.

Revision ID: 202608050005
Revises: 202608050004
Create Date: 2026-08-05 00:05:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608050005"
down_revision: str | None = "202608050004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_approved_skills",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_id", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_owner", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("audit_status", sa.String(length=64), nullable=False),
        sa.Column("audit_score", sa.Integer(), nullable=True),
        sa.Column("audit_rank", sa.String(length=32), nullable=False),
        sa.Column("audit_summary", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "metadata_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "skill_id",
            name="uq_workspace_approved_skills_workspace_skill",
        ),
    )
    op.create_index(
        op.f("ix_workspace_approved_skills_approved_by_id"),
        "workspace_approved_skills",
        ["approved_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_approved_skills_organization_id"),
        "workspace_approved_skills",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_approved_skills_status"),
        "workspace_approved_skills",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_approved_skills_workspace_id"),
        "workspace_approved_skills",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "agent_approved_skill_assignments",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_skill_id"],
            ["workspace_approved_skills.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "workspace_skill_id",
            name="uq_agent_approved_skill_assignments_agent_skill",
        ),
    )
    op.create_index(
        op.f("ix_agent_approved_skill_assignments_agent_id"),
        "agent_approved_skill_assignments",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_approved_skill_assignments_workspace_skill_id"),
        "agent_approved_skill_assignments",
        ["workspace_skill_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_agent_approved_skill_assignments_workspace_skill_id"),
        table_name="agent_approved_skill_assignments",
    )
    op.drop_index(
        op.f("ix_agent_approved_skill_assignments_agent_id"),
        table_name="agent_approved_skill_assignments",
    )
    op.drop_table("agent_approved_skill_assignments")
    op.drop_index(
        op.f("ix_workspace_approved_skills_workspace_id"),
        table_name="workspace_approved_skills",
    )
    op.drop_index(
        op.f("ix_workspace_approved_skills_status"),
        table_name="workspace_approved_skills",
    )
    op.drop_index(
        op.f("ix_workspace_approved_skills_organization_id"),
        table_name="workspace_approved_skills",
    )
    op.drop_index(
        op.f("ix_workspace_approved_skills_approved_by_id"),
        table_name="workspace_approved_skills",
    )
    op.drop_table("workspace_approved_skills")
