"""enforce unique secret store urls

Revision ID: 202606290003
Revises: 202606290002
Create Date: 2026-06-29 00:03:00.000000

"""

from alembic import op

revision = "202606290003"
down_revision = "202606290002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create unique index uq_secret_stores_org_provider_base_url
        on secret_stores (
            organization_id,
            provider,
            lower(regexp_replace(
                btrim(coalesce(config ->> 'baseUrl', config ->> 'base_url')),
                '/+$',
                ''
            ))
        )
        where provider = 'openbao'
          and coalesce(config ->> 'baseUrl', config ->> 'base_url', '') <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("uq_secret_stores_org_provider_base_url", table_name="secret_stores")
