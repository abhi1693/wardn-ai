"""split openai chatgpt provider id

Revision ID: 202606230005
Revises: 202606230004
Create Date: 2026-06-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202606230005"
down_revision: str | None = "202606230004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        update llm_provider_credentials
        set provider = 'openai_chatgpt'
        where provider = 'openai'
          and auth_method = 'oauth'
          and oauth_provider = 'chatgpt'
        """
    )
    op.execute(
        """
        update llm_provider_oauth_states
        set provider = 'openai_chatgpt'
        where provider = 'openai'
          and oauth_provider = 'chatgpt'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        update llm_provider_credentials
        set provider = 'openai'
        where provider = 'openai_chatgpt'
          and auth_method = 'oauth'
          and oauth_provider = 'chatgpt'
        """
    )
    op.execute(
        """
        update llm_provider_oauth_states
        set provider = 'openai'
        where provider = 'openai_chatgpt'
          and oauth_provider = 'chatgpt'
        """
    )
