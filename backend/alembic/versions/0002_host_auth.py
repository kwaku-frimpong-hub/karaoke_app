"""add hosts and host_auth_tokens tables

Revision ID: 0002_host_auth
Revises: 0001_initial
Create Date: 2026-08-11

M3: host accounts and their revocable bearer tokens. ``Uuid`` is the generic
SQLAlchemy type so the migration is valid on both PostgreSQL (native UUID)
and SQLite (CHAR(32)).
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_host_auth"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hosts_email", "hosts", ["email"], unique=True)

    op.create_table(
        "host_auth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_host_auth_tokens_host_id", "host_auth_tokens", ["host_id"], unique=False
    )
    op.create_index(
        "ix_host_auth_tokens_token_hash",
        "host_auth_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_host_auth_tokens_token_hash", table_name="host_auth_tokens")
    op.drop_index("ix_host_auth_tokens_host_id", table_name="host_auth_tokens")
    op.drop_table("host_auth_tokens")
    op.drop_index("ix_hosts_email", table_name="hosts")
    op.drop_table("hosts")
