"""add per-round host reordering + queue-entry skip count

Revision ID: 0008_queue_ordering
Revises: 0007_participant_cleanup
Create Date: 2026-08-14

Queue model revision: order within a round is by participant join time, the
host can reorder the current round (``round_orders`` — per-round only, the
next round resets to join order), and a skipped singer is moved to the end of
the round via ``queue_entries.skip_count`` (excluded only when they are the
only entry left so the round can complete).
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_queue_ordering"
down_revision = "0007_participant_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "queue_entries",
        sa.Column(
            "skip_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    op.create_table(
        "round_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "position", name="uq_round_orders_position"),
        sa.UniqueConstraint(
            "round_id", "participant_id", name="uq_round_orders_participant"
        ),
    )
    op.create_index(
        "ix_round_orders_round_id", "round_orders", ["round_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_round_orders_round_id", table_name="round_orders")
    op.drop_table("round_orders")
    op.drop_column("queue_entries", "skip_count")
