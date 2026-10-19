"""Persist precise word timing and per-project caption direction."""

import sqlalchemy as sa

from alembic import op

revision = "0006_precise_caption_controls"
down_revision = "0005_dynamic_caption_renders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("caption_motion", sa.String(length=16), nullable=False, server_default="pulse"),
    )
    op.add_column(
        "projects",
        sa.Column("caption_font", sa.String(length=16), nullable=False, server_default="sans"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "caption_accent", sa.String(length=7), nullable=False, server_default="#D8E25B"
        ),
    )
    op.add_column("transcript_segments", sa.Column("word_timings", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("transcript_segments", "word_timings")
    op.drop_column("projects", "caption_accent")
    op.drop_column("projects", "caption_font")
    op.drop_column("projects", "caption_motion")
