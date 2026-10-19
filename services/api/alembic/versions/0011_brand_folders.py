"""Add reusable brand folders and project render profiles."""

import sqlalchemy as sa

from alembic import op

revision = "0011_brand_folders"
down_revision = "0010_performance_caches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_folders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="tiktok"),
        sa.Column(
            "caption_motion", sa.String(length=16), nullable=False, server_default="pulse"
        ),
        sa.Column(
            "caption_font", sa.String(length=16), nullable=False, server_default="sans"
        ),
        sa.Column(
            "caption_accent", sa.String(length=7), nullable=False, server_default="#D8E25B"
        ),
        sa.Column("watermark_path", sa.Text(), nullable=True),
        sa.Column(
            "watermark_position",
            sa.String(length=24),
            nullable=False,
            server_default="upper-right",
        ),
        sa.Column(
            "watermark_size_percent", sa.Integer(), nullable=False, server_default="18"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("projects", sa.Column("brand_folder_id", sa.String(36), nullable=True))
    op.add_column(
        "projects",
        sa.Column("platform", sa.String(16), nullable=False, server_default="tiktok"),
    )
    op.add_column("projects", sa.Column("watermark_path", sa.Text(), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "watermark_position",
            sa.String(24),
            nullable=False,
            server_default="upper-right",
        ),
    )
    op.add_column(
        "projects",
        sa.Column("watermark_size_percent", sa.Integer(), nullable=False, server_default="18"),
    )
    op.create_index("ix_projects_brand_folder_id", "projects", ["brand_folder_id"])
    op.create_foreign_key(
        "fk_projects_brand_folder_id",
        "projects",
        "brand_folders",
        ["brand_folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_brand_folder_id", "projects", type_="foreignkey")
    op.drop_index("ix_projects_brand_folder_id", table_name="projects")
    op.drop_column("projects", "watermark_size_percent")
    op.drop_column("projects", "watermark_position")
    op.drop_column("projects", "watermark_path")
    op.drop_column("projects", "platform")
    op.drop_column("projects", "brand_folder_id")
    op.drop_table("brand_folders")
