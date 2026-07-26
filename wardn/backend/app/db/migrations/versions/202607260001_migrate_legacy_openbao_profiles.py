"""Migrate legacy OpenBao stores to operator-managed auth profiles.

Revision ID: 202607260001
Revises: 202607170003
Create Date: 2026-07-26 00:01:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "202607260001"
down_revision: str | None = "202607170003"
branch_labels: str | None = None
depends_on: str | None = None

LEGACY_OPENBAO_PROFILE = "legacy"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE secret_stores
            SET config = config
                    - 'authMount'
                    - 'auth_mount'
                    - 'namespace'
                    - 'tlsVerify'
                    - 'tls_verify',
                auth_config = CASE
                    WHEN nullif(btrim(auth_config ->> 'profile'), '') IS NOT NULL
                    THEN jsonb_build_object('profile', auth_config ->> 'profile')
                    ELSE jsonb_build_object('profile', '{LEGACY_OPENBAO_PROFILE}')
                END,
                updated_at = now()
            WHERE provider = 'openbao'
              AND (
                  config ?| ARRAY[
                      'authMount',
                      'auth_mount',
                      'namespace',
                      'tlsVerify',
                      'tls_verify'
                  ]
                  OR auth_config ?| ARRAY[
                      'method',
                      'role',
                      'serviceAccountTokenPath',
                      'service_account_token_path',
                      'roleIdFile',
                      'role_id_file',
                      'secretIdFile',
                      'secret_id_file'
                  ]
              )
            """
        )
    )


def downgrade() -> None:
    # The removed credential paths and transport settings were user-controlled security
    # configuration. Do not recreate them during downgrade; operators can explicitly
    # configure the legacy schema if they intentionally roll back the application.
    pass
