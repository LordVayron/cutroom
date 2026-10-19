"""Persist per-clip logo placement, caption size, and shared director defaults."""

import sqlalchemy as sa
from alembic import op

revision = "0016_director_visual_controls"
down_revision = "0015_remove_analytics_platforms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("director_defaults", sa.Text(), nullable=True))
    op.add_column("clips", sa.Column("caption_size_percent", sa.Integer(), nullable=True))
    op.add_column("clips", sa.Column("watermark_position", sa.String(24), nullable=True))
    op.add_column("clips", sa.Column("watermark_size_percent", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "watermark_size_percent")
    op.drop_column("clips", "watermark_position")
    op.drop_column("clips", "caption_size_percent")
    op.drop_column("projects", "director_defaults")
