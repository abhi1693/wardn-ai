"""Add durable lifecycle state for Wardn-managed external secrets.

Revision ID: 202607160007
Revises: 202607160006
Create Date: 2026-07-16 00:07:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607160007"
down_revision: str | None = "202607160006"
branch_labels: str | None = None
depends_on: str | None = None

MANAGED_SECRET_CANDIDATES_SQL = """
    SELECT
        h.id AS handle_id,
        'llm_provider_credential'::text AS owner_type,
        c.id AS owner_id,
        h.organization_id,
        h.workspace_id,
        h.store_id,
        h.created_by_id,
        h.purpose,
        h.external_ref
    FROM llm_provider_credentials AS c
    JOIN secret_handles AS h
      ON h.id IN (
          c.api_key_secret_handle_id,
          c.oauth_access_token_secret_handle_id,
          c.oauth_refresh_token_secret_handle_id
      )
    WHERE h.external_ref LIKE (
        'wardn/orgs/' || c.organization_id::text || '/%/llm/%'
    )
      AND h.handle_metadata ->> 'credentialName' = c.name

    UNION ALL

    SELECT
        h.id AS handle_id,
        'mcp_catalog_source'::text AS owner_type,
        s.id AS owner_id,
        h.organization_id,
        h.workspace_id,
        h.store_id,
        h.created_by_id,
        h.purpose,
        h.external_ref
    FROM mcp_catalog_sources AS s
    JOIN secret_handles AS h ON h.id = s.auth_secret_handle_id
    WHERE h.external_ref LIKE (
        'wardn/orgs/' || s.organization_id::text || '/catalog/%'
    )
      AND h.handle_metadata ->> 'provider' = 'mcp_catalog'
"""


def upgrade() -> None:
    op.create_table(
        "managed_secrets",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_type", sa.String(length=50), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="provisioning",
            nullable=False,
        ),
        sa.Column(
            "cleanup_available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cleanup_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cleanup_max_attempts", sa.Integer(), server_default="10", nullable=False),
        sa.Column("cleanup_worker_id", sa.String(length=255), server_default="", nullable=False),
        sa.Column("cleanup_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_error", sa.Text(), server_default="", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('provisioning', 'active', 'cleanup_pending', 'cleaning', 'cleanup_failed')",
            name="ck_managed_secrets_status",
        ),
        sa.CheckConstraint(
            "cleanup_attempt_count >= 0 AND cleanup_max_attempts >= 1",
            name="ck_managed_secrets_cleanup_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_managed_secrets_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_managed_secrets_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["secret_stores.id"],
            name="fk_managed_secrets_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_id",
            "external_ref",
            name="uq_managed_secrets_store_external_ref",
        ),
    )
    op.create_index(
        "ix_managed_secrets_cleanup_claimable",
        "managed_secrets",
        ["status", "cleanup_available_at", "created_at"],
    )
    op.create_index(
        "ix_managed_secrets_owner",
        "managed_secrets",
        ["owner_type", "owner_id"],
    )
    for column in (
        "organization_id",
        "workspace_id",
        "store_id",
        "created_by_id",
        "status",
        "cleanup_lease_expires_at",
    ):
        op.create_index(op.f(f"ix_managed_secrets_{column}"), "managed_secrets", [column])

    op.add_column(
        "secret_handles",
        sa.Column("managed_secret_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_secret_handles_managed_secret_id"),
        "secret_handles",
        ["managed_secret_id"],
    )
    op.create_foreign_key(
        "fk_secret_handles_managed_secret",
        "secret_handles",
        "managed_secrets",
        ["managed_secret_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Adopt only recognizable Wardn-generated paths with exactly one owner. User-supplied
    # handles remain borrowed and are intentionally left unmanaged.
    op.execute(
        sa.text(
            f"""
            WITH candidates AS (
                {MANAGED_SECRET_CANDIDATES_SQL}
            ),
            unique_paths AS (
                SELECT store_id, external_ref
                FROM candidates
                GROUP BY store_id, external_ref
                HAVING count(DISTINCT (owner_type, owner_id)) = 1
            ),
            selected AS (
                SELECT DISTINCT ON (candidate.store_id, candidate.external_ref)
                    candidate.*
                FROM candidates AS candidate
                JOIN unique_paths USING (store_id, external_ref)
                ORDER BY candidate.store_id, candidate.external_ref, candidate.handle_id
            )
            INSERT INTO managed_secrets (
                id,
                organization_id,
                workspace_id,
                store_id,
                created_by_id,
                owner_type,
                owner_id,
                purpose,
                external_ref,
                status,
                cleanup_available_at,
                cleanup_attempt_count,
                cleanup_max_attempts,
                cleanup_worker_id,
                cleanup_error
            )
            SELECT
                md5(selected.store_id::text || ':' || selected.external_ref)::uuid,
                selected.organization_id,
                selected.workspace_id,
                selected.store_id,
                selected.created_by_id,
                selected.owner_type,
                selected.owner_id,
                selected.purpose,
                selected.external_ref,
                'active',
                now(),
                0,
                10,
                '',
                ''
            FROM selected
            ON CONFLICT (store_id, external_ref) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            WITH candidates AS (
                {MANAGED_SECRET_CANDIDATES_SQL}
            )
            UPDATE secret_handles AS handle
            SET managed_secret_id = managed.id
            FROM candidates AS candidate
            JOIN managed_secrets AS managed
              ON managed.store_id = candidate.store_id
             AND managed.external_ref = candidate.external_ref
             AND managed.owner_type = candidate.owner_type
             AND managed.owner_id = candidate.owner_id
            WHERE handle.id = candidate.handle_id
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_secret_handles_managed_secret",
        "secret_handles",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_secret_handles_managed_secret_id"), table_name="secret_handles")
    op.drop_column("secret_handles", "managed_secret_id")
    op.drop_table("managed_secrets")
