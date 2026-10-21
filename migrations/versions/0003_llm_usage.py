"""Persist recorded model usage for dashboard queries."""

import sqlalchemy as sa
from alembic import op

revision = "0003_llm_usage"
down_revision = "0002_history_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("cached_input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.Column("estimated_cost_usd", sa.Numeric(24, 12)),
        sa.CheckConstraint("duration_ms >= 0", name="ck_llm_usage_duration"),
        sa.CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0", name="ck_llm_usage_cost"
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL AND cached_input_tokens IS NULL "
            "AND output_tokens IS NULL AND total_tokens IS NULL) OR "
            "(input_tokens IS NOT NULL AND cached_input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL "
            "AND input_tokens >= 0 AND cached_input_tokens >= 0 "
            "AND cached_input_tokens <= input_tokens AND output_tokens >= 0 "
            "AND total_tokens = input_tokens + output_tokens)",
            name="ck_llm_usage_tokens",
        ),
    )
    op.create_index("ix_llm_usage_started_id", "llm_usage", ["started_at", "investigation_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_started_id", table_name="llm_usage")
    op.drop_table("llm_usage")
