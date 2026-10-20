"""Create immutable investigation snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_investigations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("environment", sa.String(100), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("configured_model", sa.Text(), nullable=True),
        sa.Column("prompt_sha256", sa.String(64), nullable=True),
        sa.Column("request_payload", json_type, nullable=False),
        sa.Column("report_payload", json_type, nullable=False),
        sa.CheckConstraint("duration_ms >= 0", name="ck_investigations_duration_nonnegative"),
        sa.CheckConstraint("schema_version = 1", name="ck_investigations_schema_version"),
    )
    op.create_index(
        "ix_investigations_service_environment_created",
        "investigations",
        ["service", "environment", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_investigations_service_environment_created", table_name="investigations")
    op.drop_table("investigations")
