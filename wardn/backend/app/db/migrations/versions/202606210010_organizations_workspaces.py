"""Add organizations and workspace boundary.

Revision ID: 202606210010
Revises: 202606210009
Create Date: 2026-06-21 00:10:00.000000
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606210010"
down_revision: str | None = "202606210009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    tables = table_names()
    if "organizations" not in tables:
        op.create_table(
            "organizations",
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_organizations_created_by_id", "organizations", ["created_by_id"])
        op.create_index("ix_organizations_slug", "organizations", ["slug"])
        op.create_index("ix_organizations_status", "organizations", ["status"])

    if "organization_memberships" not in tables:
        op.create_table(
            "organization_memberships",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "user_id",
                name="uq_organization_memberships_org_user",
            ),
        )
        op.create_index(
            "ix_organization_memberships_is_active",
            "organization_memberships",
            ["is_active"],
        )
        op.create_index(
            "ix_organization_memberships_organization_id",
            "organization_memberships",
            ["organization_id"],
        )
        op.create_index("ix_organization_memberships_role", "organization_memberships", ["role"])
        op.create_index(
            "ix_organization_memberships_user_id",
            "organization_memberships",
            ["user_id"],
        )

    if "workspaces" not in tables:
        op.create_table(
            "workspaces",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "slug", name="uq_workspaces_org_slug"),
        )
        op.create_index("ix_workspaces_created_by_id", "workspaces", ["created_by_id"])
        op.create_index("ix_workspaces_organization_id", "workspaces", ["organization_id"])
        op.create_index("ix_workspaces_slug", "workspaces", ["slug"])
        op.create_index("ix_workspaces_status", "workspaces", ["status"])

    if "workspace_memberships" not in tables:
        op.create_table(
            "workspace_memberships",
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id",
                "user_id",
                name="uq_workspace_memberships_workspace_user",
            ),
        )
        op.create_index(
            "ix_workspace_memberships_is_active",
            "workspace_memberships",
            ["is_active"],
        )
        op.create_index("ix_workspace_memberships_role", "workspace_memberships", ["role"])
        op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"])
        op.create_index(
            "ix_workspace_memberships_workspace_id",
            "workspace_memberships",
            ["workspace_id"],
        )

    bind = op.get_bind()
    default_org_id = uuid4()
    default_workspace_id = uuid4()
    existing_default_org = bind.execute(
        sa.text("select id from organizations where slug = 'default'")
    ).scalar()
    if existing_default_org:
        default_org_id = existing_default_org
    else:
        bind.execute(
            sa.text(
                """
                insert into organizations (id, name, slug, status, created_at, updated_at)
                values (:id, 'Default Organization', 'default', 'active', now(), now())
                """
            ),
            {"id": default_org_id},
        )

    existing_default_workspace = bind.execute(
        sa.text(
            """
            select id from workspaces
            where organization_id = :organization_id and slug = 'default'
            """
        ),
        {"organization_id": default_org_id},
    ).scalar()
    if existing_default_workspace:
        default_workspace_id = existing_default_workspace
    else:
        bind.execute(
            sa.text(
                """
                insert into workspaces
                    (id, organization_id, name, slug, description, status, created_at, updated_at)
                values
                    (
                        :id,
                        :organization_id,
                        'Default Workspace',
                        'default',
                        '',
                        'active',
                        now(),
                        now()
                    )
                """
            ),
            {"id": default_workspace_id, "organization_id": default_org_id},
        )

    users = bind.execute(sa.text("select id, is_superuser from users")).mappings().all()
    for user in users:
        role = "owner" if user["is_superuser"] else "member"
        bind.execute(
            sa.text(
                """
                insert into organization_memberships
                    (id, organization_id, user_id, role, is_active, created_at, updated_at)
                values
                    (:id, :organization_id, :user_id, :role, true, now(), now())
                on conflict (organization_id, user_id) do nothing
                """
            ),
            {
                "id": uuid4(),
                "organization_id": default_org_id,
                "user_id": user["id"],
                "role": role,
            },
        )
        bind.execute(
            sa.text(
                """
                insert into workspace_memberships
                    (id, workspace_id, user_id, role, is_active, created_at, updated_at)
                values
                    (:id, :workspace_id, :user_id, :role, true, now(), now())
                on conflict (workspace_id, user_id) do nothing
                """
            ),
            {
                "id": uuid4(),
                "workspace_id": default_workspace_id,
                "user_id": user["id"],
                "role": role,
            },
        )

    installation_columns = column_names("mcp_server_installations")
    if "workspace_id" not in installation_columns:
        op.add_column(
            "mcp_server_installations",
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_index(
            "ix_mcp_server_installations_workspace_id",
            "mcp_server_installations",
            ["workspace_id"],
        )
        op.create_foreign_key(
            "fk_mcp_server_installations_workspace_id_workspaces",
            "mcp_server_installations",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )

    bind.execute(
        sa.text(
            """
            update mcp_server_installations
            set workspace_id = :workspace_id
            where workspace_id is null
            """
        ),
        {"workspace_id": default_workspace_id},
    )

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("mcp_server_installations")
    for constraint in unique_constraints:
        if constraint.get("name") == "uq_mcp_server_installations_server_config":
            op.drop_constraint(
                "uq_mcp_server_installations_server_config",
                "mcp_server_installations",
                type_="unique",
            )

    existing_constraints = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("mcp_server_installations")
    }
    if "uq_mcp_server_installations_workspace_server_config" not in existing_constraints:
        op.create_unique_constraint(
            "uq_mcp_server_installations_workspace_server_config",
            "mcp_server_installations",
            ["workspace_id", "server_name", "config_name"],
        )
    op.alter_column("mcp_server_installations", "workspace_id", nullable=False)

    for table_name in ("mcp_runtime_sessions", "mcp_tool_invocations"):
        if table_name not in table_names():
            continue
        columns = column_names(table_name)
        if "organization_id" not in columns:
            op.add_column(
                table_name,
                sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_index(f"ix_{table_name}_organization_id", table_name, ["organization_id"])
            op.create_foreign_key(
                f"fk_{table_name}_organization_id_organizations",
                table_name,
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "workspace_id" not in columns:
            op.add_column(
                table_name,
                sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_index(f"ix_{table_name}_workspace_id", table_name, ["workspace_id"])
            op.create_foreign_key(
                f"fk_{table_name}_workspace_id_workspaces",
                table_name,
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="SET NULL",
            )
        bind.execute(
            sa.text(
                f"""
                update {table_name} target
                set
                    workspace_id = installation.workspace_id,
                    organization_id = workspace.organization_id
                from mcp_server_installations installation
                join workspaces workspace on workspace.id = installation.workspace_id
                where target.installation_id = installation.id
                  and target.workspace_id is null
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("mcp_server_installations")
    if any(
        constraint.get("name") == "uq_mcp_server_installations_workspace_server_config"
        for constraint in unique_constraints
    ):
        op.drop_constraint(
            "uq_mcp_server_installations_workspace_server_config",
            "mcp_server_installations",
            type_="unique",
        )
    if not any(
        constraint.get("name") == "uq_mcp_server_installations_server_config"
        for constraint in unique_constraints
    ):
        op.create_unique_constraint(
            "uq_mcp_server_installations_server_config",
            "mcp_server_installations",
            ["server_name", "config_name"],
        )

    for table_name in ("mcp_tool_invocations", "mcp_runtime_sessions"):
        if table_name in table_names():
            columns = column_names(table_name)
            if "workspace_id" in columns:
                op.drop_column(table_name, "workspace_id")
            if "organization_id" in columns:
                op.drop_column(table_name, "organization_id")

    if "workspace_id" in column_names("mcp_server_installations"):
        op.drop_column("mcp_server_installations", "workspace_id")

    for table_name in (
        "workspace_memberships",
        "workspaces",
        "organization_memberships",
        "organizations",
    ):
        if table_name in table_names():
            op.drop_table(table_name)
