"""Version renders for stable framing and burned-in dynamic captions."""

import sqlalchemy as sa

from alembic import op

revision = "0005_dynamic_caption_renders"
down_revision = "0004_clip_memory_and_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clips",
        sa.Column("render_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("clips", "render_version")
