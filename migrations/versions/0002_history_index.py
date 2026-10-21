"""Index history ordered by creation time and UUID."""

from alembic import op

revision = "0002_history_index"
down_revision = "0001_investigations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_investigations_created_id", "investigations", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_investigations_created_id", table_name="investigations")
