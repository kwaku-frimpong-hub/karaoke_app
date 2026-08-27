"""add participants table

Revision ID: 0004_participants
Revises: 0003_sessions
Create Date: 2026-08-11

M5: session-scoped participant identities for the public join flow. Only the
SHA-256 digest of the participant's opaque token is stored (D25 pattern).
Nickname uniqueness is case-insensitive per session via the ``nickname_lower``
column (B14/D16).
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_participants"
down_revision = "0003_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.String(length=20), nullable=False),
        sa.Column("nickname_lower", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "nickname_lower", name="uq_participants_session_nickname"
        ),
    )
    op.create_index(
        "ix_participants_session_id", "participants", ["session_id"], unique=False
    )
    op.create_index(
        "ix_participants_token_hash", "participants", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_participants_token_hash", table_name="participants")
    op.drop_index("ix_participants_session_id", table_name="participants")
    op.drop_table("participants")
