"""Add non-destructive per-clip Director Mode edits."""

import sqlalchemy as sa

from alembic import op

revision = "0007_director_mode"
down_revision = "0006_precise_caption_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clips", sa.Column("original_start_seconds", sa.Float(), nullable=True))
    op.add_column("clips", sa.Column("original_end_seconds", sa.Float(), nullable=True))
    op.execute(
        "UPDATE clips SET original_start_seconds = start_seconds, "
        "original_end_seconds = end_seconds"
    )
    op.alter_column("clips", "original_start_seconds", nullable=False)
    op.alter_column("clips", "original_end_seconds", nullable=False)
    op.add_column("clips", sa.Column("caption_overrides", sa.Text(), nullable=True))
    op.add_column(
        "clips",
        sa.Column("speaker_focus", sa.String(length=16), nullable=False, server_default="auto"),
    )
    op.add_column(
        "clips",
        sa.Column("caption_position", sa.String(length=16), nullable=False, server_default="lower"),
    )
    op.add_column(
        "clips", sa.Column("edit_revision", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("clips", "edit_revision")
    op.drop_column("clips", "caption_position")
    op.drop_column("clips", "speaker_focus")
    op.drop_column("clips", "caption_overrides")
    op.drop_column("clips", "original_end_seconds")
    op.drop_column("clips", "original_start_seconds")
