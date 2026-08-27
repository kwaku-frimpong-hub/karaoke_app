"""add queue tables: youtube_videos, rounds, queue_entries

Revision ID: 0005_queue
Revises: 0004_participants
Create Date: 2026-08-11

M7: the authoritative queue engine. ``youtube_videos`` holds one metadata
snapshot per unique video id; ``rounds`` holds the numbered rounds (round 1 is
created with the session); ``queue_entries`` references a session, round,
participant, and youtube video with a non-native enum status (D22).
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_queue"
down_revision = "0004_participants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_videos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("youtube_video_id", sa.String(length=11), nullable=False),
        sa.Column("youtube_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=200), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=2048), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_youtube_videos_youtube_video_id",
        "youtube_videos",
        ["youtube_video_id"],
        unique=True,
    )

    op.create_table(
        "rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "number", name="uq_rounds_session_number"),
    )
    op.create_index("ix_rounds_session_id", "rounds", ["session_id"], unique=False)

    op.create_table(
        "queue_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("youtube_video_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "WAITING",
                "NEXT",
                "SINGING",
                "COMPLETED",
                "SKIPPED",
                "CANCELLED",
                "REMOVED",
                name="queue_entry_status",
                native_enum=False,
                length=32,
            ),
            server_default="WAITING",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["youtube_video_id"], ["youtube_videos.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_queue_entries_session_id", "queue_entries", ["session_id"], unique=False
    )
    op.create_index(
        "ix_queue_entries_round_id", "queue_entries", ["round_id"], unique=False
    )
    op.create_index(
        "ix_queue_entries_participant_id",
        "queue_entries",
        ["participant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_queue_entries_participant_id", table_name="queue_entries")
    op.drop_index("ix_queue_entries_round_id", table_name="queue_entries")
    op.drop_index("ix_queue_entries_session_id", table_name="queue_entries")
    op.drop_table("queue_entries")
    op.drop_index("ix_rounds_session_id", table_name="rounds")
    op.drop_table("rounds")
    op.drop_index("ix_youtube_videos_youtube_video_id", table_name="youtube_videos")
    op.drop_table("youtube_videos")
