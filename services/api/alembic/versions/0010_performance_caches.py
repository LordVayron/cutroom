"""Cache analysis and speaker tracking artifacts."""

import sqlalchemy as sa

from alembic import op

revision = "0010_performance_caches"
down_revision = "0009_quality_inspector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("analysis_cache_key", sa.String(length=64), nullable=True)
    )
    op.add_column("projects", sa.Column("analysis_cache_payload", sa.Text(), nullable=True))
    op.add_column(
        "clips", sa.Column("tracking_cache_key", sa.String(length=64), nullable=True)
    )
    op.add_column("clips", sa.Column("tracking_crop_expression", sa.Text(), nullable=True))
    op.add_column(
        "clips", sa.Column("tracking_detection_count", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clips", "tracking_detection_count")
    op.drop_column("clips", "tracking_crop_expression")
    op.drop_column("clips", "tracking_cache_key")
    op.drop_column("projects", "analysis_cache_payload")
    op.drop_column("projects", "analysis_cache_key")
