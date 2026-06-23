"""split agent tool assignments by mcp server

Revision ID: 202606230007
Revises: 202606230006
Create Date: 2026-06-23
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230007"
down_revision: str | None = "202606230006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_mcp_server_assignments",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "installation_id",
            name="uq_agent_mcp_server_assignments_agent_installation",
        ),
    )
    op.create_index(
        op.f("ix_agent_mcp_server_assignments_agent_id"),
        "agent_mcp_server_assignments",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_mcp_server_assignments_installation_id"),
        "agent_mcp_server_assignments",
        ["installation_id"],
        unique=False,
    )

    op.create_table(
        "agent_mcp_tool_assignments",
        sa.Column("server_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_schema_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("wildcard", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint(
            "(wildcard = true and tool_schema_id is null) "
            "or (wildcard = false and tool_schema_id is not null)",
            name="ck_agent_mcp_tool_assignments_wildcard_shape",
        ),
        sa.ForeignKeyConstraint(
            ["server_assignment_id"],
            ["agent_mcp_server_assignments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_schema_id"],
            ["mcp_server_tool_schemas.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_assignment_id",
            "tool_schema_id",
            name="uq_agent_mcp_tool_assignments_server_tool_schema",
        ),
    )
    op.create_index(
        op.f("ix_agent_mcp_tool_assignments_server_assignment_id"),
        "agent_mcp_tool_assignments",
        ["server_assignment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_mcp_tool_assignments_tool_schema_id"),
        "agent_mcp_tool_assignments",
        ["tool_schema_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_mcp_tool_assignments_wildcard"),
        "agent_mcp_tool_assignments",
        ["wildcard"],
        unique=False,
    )
    op.create_index(
        "uq_agent_mcp_tool_assignments_server_wildcard",
        "agent_mcp_tool_assignments",
        ["server_assignment_id"],
        unique=True,
        postgresql_where=sa.text("wildcard is true"),
    )

    connection = op.get_bind()
    agent_tools = sa.table(
        "agent_tools",
        sa.column("agent_id", postgresql.UUID(as_uuid=True)),
        sa.column("tool_schema_id", postgresql.UUID(as_uuid=True)),
        sa.column("installation_id", postgresql.UUID(as_uuid=True)),
    )
    server_assignments = sa.table(
        "agent_mcp_server_assignments",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("agent_id", postgresql.UUID(as_uuid=True)),
        sa.column("installation_id", postgresql.UUID(as_uuid=True)),
    )
    tool_assignments = sa.table(
        "agent_mcp_tool_assignments",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("server_assignment_id", postgresql.UUID(as_uuid=True)),
        sa.column("tool_schema_id", postgresql.UUID(as_uuid=True)),
        sa.column("wildcard", sa.Boolean()),
    )
    rows = connection.execute(
        sa.select(
            agent_tools.c.agent_id,
            agent_tools.c.installation_id,
            agent_tools.c.tool_schema_id,
        )
    ).all()
    assignment_ids: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
    for agent_id, installation_id, tool_schema_id in rows:
        key = (agent_id, installation_id)
        server_assignment_id = assignment_ids.get(key)
        if server_assignment_id is None:
            server_assignment_id = uuid.uuid4()
            assignment_ids[key] = server_assignment_id
            connection.execute(
                server_assignments.insert().values(
                    id=server_assignment_id,
                    agent_id=agent_id,
                    installation_id=installation_id,
                )
            )
        connection.execute(
            tool_assignments.insert().values(
                id=uuid.uuid4(),
                server_assignment_id=server_assignment_id,
                tool_schema_id=tool_schema_id,
                wildcard=False,
            )
        )

    op.drop_index(op.f("ix_agent_tools_tool_schema_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_installation_id"), table_name="agent_tools")
    op.drop_index(op.f("ix_agent_tools_agent_id"), table_name="agent_tools")
    op.drop_table("agent_tools")


def downgrade() -> None:
    op.create_table(
        "agent_tools",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_schema_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["mcp_server_installations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_schema_id"],
            ["mcp_server_tool_schemas.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "tool_schema_id", name="uq_agent_tools_agent_tool_schema"),
    )
    op.create_index(op.f("ix_agent_tools_agent_id"), "agent_tools", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_agent_tools_installation_id"),
        "agent_tools",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_tools_tool_schema_id"),
        "agent_tools",
        ["tool_schema_id"],
        unique=False,
    )

    connection = op.get_bind()
    server_assignments = sa.table(
        "agent_mcp_server_assignments",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("agent_id", postgresql.UUID(as_uuid=True)),
        sa.column("installation_id", postgresql.UUID(as_uuid=True)),
    )
    tool_assignments = sa.table(
        "agent_mcp_tool_assignments",
        sa.column("server_assignment_id", postgresql.UUID(as_uuid=True)),
        sa.column("tool_schema_id", postgresql.UUID(as_uuid=True)),
        sa.column("wildcard", sa.Boolean()),
    )
    tool_schemas = sa.table(
        "mcp_server_tool_schemas",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("installation_id", postgresql.UUID(as_uuid=True)),
        sa.column("is_active", sa.Boolean()),
    )
    agent_tools = sa.table(
        "agent_tools",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("agent_id", postgresql.UUID(as_uuid=True)),
        sa.column("tool_schema_id", postgresql.UUID(as_uuid=True)),
        sa.column("installation_id", postgresql.UUID(as_uuid=True)),
    )
    explicit_rows = connection.execute(
        sa.select(
            server_assignments.c.agent_id,
            server_assignments.c.installation_id,
            tool_assignments.c.tool_schema_id,
        )
        .select_from(
            server_assignments.join(
                tool_assignments,
                tool_assignments.c.server_assignment_id == server_assignments.c.id,
            )
        )
        .where(tool_assignments.c.wildcard.is_(False))
    ).all()
    wildcard_rows = connection.execute(
        sa.select(
            server_assignments.c.agent_id,
            server_assignments.c.installation_id,
            tool_schemas.c.id,
        )
        .select_from(
            server_assignments.join(
                tool_assignments,
                tool_assignments.c.server_assignment_id == server_assignments.c.id,
            ).join(
                tool_schemas,
                tool_schemas.c.installation_id == server_assignments.c.installation_id,
            )
        )
        .where(tool_assignments.c.wildcard.is_(True), tool_schemas.c.is_active.is_(True))
    ).all()
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for agent_id, installation_id, tool_schema_id in [*explicit_rows, *wildcard_rows]:
        key = (agent_id, tool_schema_id)
        if key in seen:
            continue
        seen.add(key)
        connection.execute(
            agent_tools.insert().values(
                id=uuid.uuid4(),
                agent_id=agent_id,
                installation_id=installation_id,
                tool_schema_id=tool_schema_id,
            )
        )

    op.drop_index(
        "uq_agent_mcp_tool_assignments_server_wildcard",
        table_name="agent_mcp_tool_assignments",
    )
    op.drop_index(
        op.f("ix_agent_mcp_tool_assignments_wildcard"),
        table_name="agent_mcp_tool_assignments",
    )
    op.drop_index(
        op.f("ix_agent_mcp_tool_assignments_tool_schema_id"),
        table_name="agent_mcp_tool_assignments",
    )
    op.drop_index(
        op.f("ix_agent_mcp_tool_assignments_server_assignment_id"),
        table_name="agent_mcp_tool_assignments",
    )
    op.drop_table("agent_mcp_tool_assignments")
    op.drop_index(
        op.f("ix_agent_mcp_server_assignments_installation_id"),
        table_name="agent_mcp_server_assignments",
    )
    op.drop_index(
        op.f("ix_agent_mcp_server_assignments_agent_id"),
        table_name="agent_mcp_server_assignments",
    )
    op.drop_table("agent_mcp_server_assignments")
