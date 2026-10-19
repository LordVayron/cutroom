"""Persist automatic post-render quality inspection reports."""

import sqlalchemy as sa

from alembic import op

revision = "0009_quality_inspector"
down_revision = "0008_director_caption_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clips",
        sa.Column(
            "quality_status",
            sa.String(length=16),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.add_column("clips", sa.Column("quality_score", sa.Integer(), nullable=True))
    op.add_column("clips", sa.Column("quality_report", sa.Text(), nullable=True))
    op.add_column(
        "clips", sa.Column("quality_checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clips", "quality_checked_at")
    op.drop_column("clips", "quality_report")
    op.drop_column("clips", "quality_score")
    op.drop_column("clips", "quality_status")
