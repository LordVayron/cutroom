"""Persist hook repair suggestions and generated cover options."""

import sqlalchemy as sa

from alembic import op

revision = "0012_hook_repair_covers"
down_revision = "0011_brand_folders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clips",
        sa.Column(
            "hook_repair_status",
            sa.String(length=16),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.add_column("clips", sa.Column("hook_repair_start", sa.Float(), nullable=True))
    op.add_column("clips", sa.Column("hook_repair_end", sa.Float(), nullable=True))
    op.add_column("clips", sa.Column("hook_repair_opening_note", sa.Text(), nullable=True))
    op.add_column("clips", sa.Column("hook_repair_ending_note", sa.Text(), nullable=True))
    op.add_column("clips", sa.Column("cover_options", sa.Text(), nullable=True))
    op.add_column("clips", sa.Column("selected_cover_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "selected_cover_index")
    op.drop_column("clips", "cover_options")
    op.drop_column("clips", "hook_repair_ending_note")
    op.drop_column("clips", "hook_repair_opening_note")
    op.drop_column("clips", "hook_repair_end")
    op.drop_column("clips", "hook_repair_start")
    op.drop_column("clips", "hook_repair_status")
