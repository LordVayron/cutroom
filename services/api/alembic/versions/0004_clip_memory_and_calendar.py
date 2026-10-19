"""Remember prior clip generations and add the publishing calendar."""

import sqlalchemy as sa

from alembic import op

revision = "0004_clip_memory_and_calendar"
down_revision = "0003_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("requested_clip_count", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column(
        "projects",
        sa.Column("analysis_generation", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "clips", sa.Column("generation", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "clips", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("clips", sa.Column("series_id", sa.String(length=80), nullable=True))
    op.add_column("clips", sa.Column("series_index", sa.Integer(), nullable=True))
    op.add_column("clips", sa.Column("series_count", sa.Integer(), nullable=True))
    op.drop_constraint("uq_clips_project_rank", "clips", type_="unique")
    op.create_unique_constraint(
        "uq_clips_project_generation_rank", "clips", ["project_id", "generation", "rank"]
    )
    op.create_table(
        "publication_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("clip_id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cover_title", sa.String(length=80), nullable=False),
        sa.Column("seo_caption", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["clip_id"], ["clips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clip_id"),
    )
    op.create_index(
        "ix_publication_schedules_project_id",
        "publication_schedules",
        ["project_id"],
    )
    op.create_index(
        "ix_publication_queue", "publication_schedules", ["status", "scheduled_for"]
    )


def downgrade() -> None:
    op.drop_index("ix_publication_queue", table_name="publication_schedules")
    op.drop_index("ix_publication_schedules_project_id", table_name="publication_schedules")
    op.drop_table("publication_schedules")
    op.execute("DELETE FROM clips WHERE is_current = false")
    op.drop_constraint("uq_clips_project_generation_rank", "clips", type_="unique")
    op.create_unique_constraint("uq_clips_project_rank", "clips", ["project_id", "rank"])
    op.drop_column("clips", "series_count")
    op.drop_column("clips", "series_index")
    op.drop_column("clips", "series_id")
    op.drop_column("clips", "is_current")
    op.drop_column("clips", "generation")
    op.drop_column("projects", "analysis_generation")
    op.drop_column("projects", "requested_clip_count")
