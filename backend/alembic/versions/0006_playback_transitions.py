"""add playback transition columns to sessions

Revision ID: 0006_playback_transitions
Revises: 0005_queue
Create Date: 2026-08-13

M13 (automatic song transitions): sessions gain the stored playback state
(superseding the M11/D46 derived state — COOLDOWN/COUNTDOWN cannot be derived
from entry statuses alone), the authoritative transition deadline, and the
per-session transition timings (defaults from settings, PRODUCT_SPEC §10).
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_playback_transitions"
down_revision = "0005_queue"
branch_labels = None
depends_on = None

_PLAYBACK_STATES = (
    "IDLE",
    "PREPARING",
    "COUNTDOWN",
    "PLAYING",
    "COOLDOWN",
    "FINISHED",
    "SKIPPED",
)


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "playback_state",
            sa.Enum(
                *_PLAYBACK_STATES,
                name="playback_state",
                native_enum=False,
                length=32,
            ),
            server_default="IDLE",
            nullable=False,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("transition_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "cooldown_seconds",
            sa.Integer(),
            server_default=sa.text("10"),
            nullable=False,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "countdown_seconds",
            sa.Integer(),
            server_default=sa.text("20"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "countdown_seconds")
    op.drop_column("sessions", "cooldown_seconds")
    op.drop_column("sessions", "transition_until")
    op.drop_column("sessions", "playback_state")
