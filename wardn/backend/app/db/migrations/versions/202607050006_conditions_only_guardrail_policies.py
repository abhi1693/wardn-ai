"""make guardrail policies conditions-only

Revision ID: 202607050006
Revises: 202607050005
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607050006"
down_revision: str | None = "202607050005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        update guardrail_policies
        set conditions = jsonb_build_object(
            'operator',
            'all',
            'rules',
            jsonb_build_array(
                jsonb_build_object(
                    'field', 'tool_schema_id',
                    'operator', 'equals',
                    'value', tool_schema_id::text
                )
            )
        )
        where conditions = '{}'::jsonb
          and tool_schema_id is not null
        """
    )
    op.execute(
        """
        with installation_tool_rules as (
            select
                policies.id as policy_id,
                coalesce(
                    jsonb_agg(tool_schemas.id::text)
                        filter (where tool_schemas.id is not null),
                    jsonb_build_array('__no_matching_tool__')
                ) as tool_schema_ids
            from guardrail_policies policies
            left join mcp_server_tool_schemas tool_schemas
                on tool_schemas.installation_id = policies.installation_id
            where policies.conditions = '{}'::jsonb
              and policies.tool_schema_id is null
              and policies.installation_id is not null
            group by policies.id
        )
        update guardrail_policies policies
        set conditions = jsonb_build_object(
            'operator',
            'all',
            'rules',
            jsonb_build_array(
                jsonb_build_object(
                    'field', 'tool_schema_id',
                    'operator', 'in',
                    'value', installation_tool_rules.tool_schema_ids
                )
            )
        )
        from installation_tool_rules
        where policies.id = installation_tool_rules.policy_id
        """
    )
    op.execute("drop index if exists ix_guardrail_policies_targets")
    op.execute("drop index if exists ix_guardrail_policies_agent_id")
    op.execute("drop index if exists ix_guardrail_policies_installation_id")
    op.execute("drop index if exists ix_guardrail_policies_tool_schema_id")
    op.execute(
        "alter table guardrail_policies "
        "drop constraint if exists guardrail_policies_agent_id_fkey"
    )
    op.execute(
        "alter table guardrail_policies "
        "drop constraint if exists guardrail_policies_installation_id_fkey"
    )
    op.execute(
        "alter table guardrail_policies "
        "drop constraint if exists guardrail_policies_tool_schema_id_fkey"
    )
    op.drop_column("guardrail_policies", "agent_id")
    op.drop_column("guardrail_policies", "installation_id")
    op.drop_column("guardrail_policies", "tool_schema_id")


def downgrade() -> None:
    op.add_column(
        "guardrail_policies",
        sa.Column("tool_schema_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "guardrail_policies",
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "guardrail_policies",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "guardrail_policies_agent_id_fkey",
        "guardrail_policies",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "guardrail_policies_installation_id_fkey",
        "guardrail_policies",
        "mcp_server_installations",
        ["installation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "guardrail_policies_tool_schema_id_fkey",
        "guardrail_policies",
        "mcp_server_tool_schemas",
        ["tool_schema_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_guardrail_policies_agent_id", "guardrail_policies", ["agent_id"])
    op.create_index(
        "ix_guardrail_policies_installation_id",
        "guardrail_policies",
        ["installation_id"],
    )
    op.create_index(
        "ix_guardrail_policies_tool_schema_id",
        "guardrail_policies",
        ["tool_schema_id"],
    )
    op.create_index(
        "ix_guardrail_policies_targets",
        "guardrail_policies",
        ["agent_id", "installation_id", "tool_schema_id"],
    )
