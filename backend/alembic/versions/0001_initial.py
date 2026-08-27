"""initial empty schema

M2 note: the backend skeleton is in place but no domain models exist yet,
so this initial migration creates no tables. It anchors the Alembic revision
chain; domain tables arrive with M4+ as models are added to app.models.
"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: no domain tables exist at M2."""
    pass


def downgrade() -> None:
    """No-op: no domain tables exist at M2."""
    pass
