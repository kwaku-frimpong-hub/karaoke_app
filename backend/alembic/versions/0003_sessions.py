"""add sessions table

Revision ID: 0003_sessions
Revises: 0002_host_auth
Create Date: 2026-08-11

M4: host-owned karaoke sessions. The status column stores the
``SessionStatus`` enum value as a non-native VARCHAR so the migration is valid
on both PostgreSQL and SQLite (decision D22).
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_sessions"
down_revision = "0002_host_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("join_code", sa.String(length=8), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "CREATED",
                "ACTIVE",
                "PAUSED",
                "ROUND_COMPLETE",
                "ENDED",
                name="session_status",
                native_enum=False,
                length=32,
            ),
            server_default="CREATED",
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
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_host_id", "sessions", ["host_id"], unique=False)
    op.create_index("ix_sessions_join_code", "sessions", ["join_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sessions_join_code", table_name="sessions")
    op.drop_index("ix_sessions_host_id", table_name="sessions")
    op.drop_table("sessions")
