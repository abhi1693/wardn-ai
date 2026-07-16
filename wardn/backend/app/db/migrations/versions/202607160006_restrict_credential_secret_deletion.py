"""Restrict deletion of credential secret handles.

Revision ID: 202607160006
Revises: 202607160005
Create Date: 2026-07-16 00:06:00.000000
"""

from alembic import op

revision: str = "202607160006"
down_revision: str | None = "202607160005"
branch_labels: str | None = None
depends_on: str | None = None


SECRET_HANDLE_FOREIGN_KEYS = (
    (
        "fk_llm_provider_credentials_api_key_secret_handle",
        "api_key_secret_handle_id",
    ),
    (
        "fk_llm_provider_credentials_oauth_access_secret_handle",
        "oauth_access_token_secret_handle_id",
    ),
    (
        "fk_llm_provider_credentials_oauth_refresh_secret_handle",
        "oauth_refresh_token_secret_handle_id",
    ),
)


def replace_secret_handle_foreign_keys(*, ondelete: str) -> None:
    for constraint_name, column_name in SECRET_HANDLE_FOREIGN_KEYS:
        op.drop_constraint(
            constraint_name,
            "llm_provider_credentials",
            type_="foreignkey",
        )
        op.create_foreign_key(
            constraint_name,
            "llm_provider_credentials",
            "secret_handles",
            [column_name],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    replace_secret_handle_foreign_keys(ondelete="RESTRICT")


def downgrade() -> None:
    replace_secret_handle_foreign_keys(ondelete="SET NULL")
