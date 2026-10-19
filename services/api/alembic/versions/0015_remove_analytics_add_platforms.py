"""Remove manual analytics and add publication platform selection."""

import sqlalchemy as sa

from alembic import op

revision = "0015_remove_analytics_platforms"
down_revision = "0014_analytics_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publication_schedules",
        sa.Column("platforms", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE publication_schedules AS publication
        SET platforms = '["' || project.platform || '"]'
        FROM projects AS project
        WHERE publication.project_id = project.id
        """
    )
    op.alter_column("publication_schedules", "platforms", nullable=False)
    op.drop_table("clip_analytics")


def downgrade() -> None:
    op.create_table(
        "clip_analytics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "clip_id",
            sa.String(36),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("source_key", sa.String(120), nullable=False, server_default="current"),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watch_time_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_watch_percentage", sa.Float(), nullable=True),
        sa.Column("completion_rate", sa.Float(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saves", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("followers_gained", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("performance_score", sa.Float(), nullable=False, server_default="50"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "clip_id", "platform", "source_key", name="uq_clip_analytics_source"
        ),
    )
    op.create_index("ix_clip_analytics_clip_id", "clip_analytics", ["clip_id"])
    op.create_index(
        "ix_clip_analytics_captured",
        "clip_analytics",
        ["clip_id", "captured_at"],
    )
    op.drop_column("publication_schedules", "platforms")
