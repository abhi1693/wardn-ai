"""Append-only execution evidence and resumable workspace consumers.

Revision ID: 202609070001
Revises: 202609020001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "202609070001"
down_revision = "202609020001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_event_streams",
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "learning_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_kind", sa.String(32), nullable=False),
        *[
            sa.Column(name, pg.UUID(as_uuid=True), nullable=True)
            for name in (
                "agent_id",
                "conversation_id",
                "objective_id",
                "scheduled_task_id",
                "scheduled_run_id",
                "parent_event_id",
                "tool_call_id",
            )
        ],
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("workspace_sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("span_id", sa.String(32), nullable=False),
        sa.Column("data", pg.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "execution_id", "sequence_number", name="uq_learning_execution_sequence"
        ),
        sa.UniqueConstraint(
            "workspace_id", "workspace_sequence", name="uq_learning_workspace_sequence"
        ),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_learning_event_idempotency"
        ),
        sa.CheckConstraint(
            "sequence_number > 0 AND workspace_sequence > 0", name="ck_learning_sequence"
        ),
        sa.CheckConstraint(
            "execution_kind IN ('agent_run', 'scheduled_run', 'tool_invocation')",
            name="ck_learning_execution_kind",
        ),
    )
    for name, columns in (
        ("workspace_occurred", ["workspace_id", "occurred_at"]),
        ("conversation_occurred", ["conversation_id", "occurred_at"]),
        ("type_occurred", ["event_type", "occurred_at"]),
        ("objective", ["objective_id"]),
        ("tool_call", ["tool_call_id"]),
        ("scheduled_run", ["scheduled_run_id"]),
    ):
        op.create_index(f"ix_learning_{name}", "learning_events", columns)
    op.create_table(
        "learning_worker_cursors",
        sa.Column("worker_name", sa.String(100), primary_key=True),
        sa.Column(
            "workspace_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_event_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("last_sequence >= 0", name="ck_learning_cursor_sequence"),
    )
    op.execute("""
        CREATE FUNCTION wardn_learning_validate_workspace() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.id = NEW.workspace_id
                           AND w.organization_id = NEW.organization_id) THEN
                RAISE EXCEPTION 'learning workspace organization mismatch';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("learning_events", "learning_event_streams", "learning_worker_cursors"):
        op.execute(f"""
            CREATE TRIGGER learning_workspace_check BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION wardn_learning_validate_workspace()
        """)
    op.execute("""
        CREATE FUNCTION wardn_learning_immutable_event() RETURNS trigger AS $$
        BEGIN
            -- Explicit workspace deletion is the privacy/tenant teardown boundary.
            -- Ordinary source-record pruning cannot change these provenance records.
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'learning events are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER learning_events_immutable BEFORE UPDATE OR DELETE ON learning_events
        FOR EACH ROW EXECUTE FUNCTION wardn_learning_immutable_event()
    """)


def downgrade() -> None:
    op.drop_table("learning_worker_cursors")
    op.drop_table("learning_events")
    op.drop_table("learning_event_streams")
    op.execute("DROP FUNCTION wardn_learning_immutable_event()")
    op.execute("DROP FUNCTION wardn_learning_validate_workspace()")
