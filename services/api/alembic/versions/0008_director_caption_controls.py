"""Add per-clip Director Mode caption controls."""

import sqlalchemy as sa

from alembic import op

revision = "0008_director_caption_controls"
down_revision = "0007_director_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clips", sa.Column("caption_motion", sa.String(length=16), nullable=True))
    op.add_column("clips", sa.Column("caption_font", sa.String(length=16), nullable=True))
    op.add_column("clips", sa.Column("caption_accent", sa.String(length=7), nullable=True))
    op.add_column("clips", sa.Column("caption_words_per_phrase", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "caption_words_per_phrase")
    op.drop_column("clips", "caption_accent")
    op.drop_column("clips", "caption_font")
    op.drop_column("clips", "caption_motion")
