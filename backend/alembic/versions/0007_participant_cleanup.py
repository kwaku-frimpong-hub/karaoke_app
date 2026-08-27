"""add participants.last_connected_at

Revision ID: 0007_participant_cleanup
Revises: 0006_playback_transitions
Create Date: 2026-08-13

M16 (round lifecycle cleanup): track when a participant last connected to the
realtime channel so the backend can clean up the remaining WAITING songs of
participants who have left (absent-participant cleanup). NULL means "never
tracked" — such participants are treated as present (never cleaned).
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_participant_cleanup"
down_revision = "0006_playback_transitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("participants", "last_connected_at")
