"""duplicate protection, idempotency keys, alert rules and alerts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

operator_enum = sa.Enum("gt", "lt", name="alert_operator")
status_enum = sa.Enum("open", "resolved", name="alert_status")


def upgrade() -> None:
    # The unique constraint's index covers (device_id, metric, ts), so the old index is redundant.
    # Existing duplicate rows would make this fail; there are none before this revision in practice,
    # but check with a GROUP BY ... HAVING count(*) > 1 before running it on real data.
    with op.batch_alter_table("readings") as batch:
        batch.drop_index("ix_readings_device_metric_ts")
        batch.create_unique_constraint(
            "uq_readings_device_metric_ts", ["device_id", "metric", "ts"]
        )
        batch.add_column(
            sa.Column("alert_checked", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Readings stored before the worker existed are treated as already checked.
    op.execute(sa.text("UPDATE readings SET alert_checked = true"))
    op.create_index(
        "ix_readings_unchecked",
        "readings",
        ["ts"],
        postgresql_where=sa.text("NOT alert_checked"),
        sqlite_where=sa.text("NOT alert_checked"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column(
            "device_id",
            sa.Uuid(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("operator", operator_enum, nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_rules_metric", "alert_rules", ["metric"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.Uuid(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("trigger_value", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_alerts_one_open",
        "alerts",
        ["rule_id", "device_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_one_open", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_alert_rules_metric", table_name="alert_rules")
    op.drop_table("alert_rules")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_readings_unchecked", table_name="readings")
    with op.batch_alter_table("readings") as batch:
        batch.drop_column("alert_checked")
        batch.drop_constraint("uq_readings_device_metric_ts", type_="unique")
        batch.create_index("ix_readings_device_metric_ts", ["device_id", "metric", "ts"])
    status_enum.drop(op.get_bind(), checkfirst=True)
    operator_enum.drop(op.get_bind(), checkfirst=True)
