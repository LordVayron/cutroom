"""Persist editorial feedback and cross-project concept memory."""

import sqlalchemy as sa

from alembic import op

revision = "0013_taste_learning"
down_revision = "0012_hook_repair_covers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "duplicate_ideas_filtered",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("clips", sa.Column("feedback_decision", sa.String(16), nullable=True))
    op.add_column("clips", sa.Column("feedback_reason", sa.String(32), nullable=True))
    op.add_column("clips", sa.Column("feedback_detail", sa.Text(), nullable=True))
    op.add_column("clips", sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clips", sa.Column("concept_signature", sa.Text(), nullable=True))
    op.create_index("ix_clips_feedback_decision", "clips", ["feedback_decision"])


def downgrade() -> None:
    op.drop_index("ix_clips_feedback_decision", table_name="clips")
    op.drop_column("clips", "concept_signature")
    op.drop_column("clips", "feedback_at")
    op.drop_column("clips", "feedback_detail")
    op.drop_column("clips", "feedback_reason")
    op.drop_column("clips", "feedback_decision")
    op.drop_column("projects", "duplicate_ideas_filtered")
