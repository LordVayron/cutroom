"""Add reversible library lifecycle flags without removing media."""

import sqlalchemy as sa

from alembic import op

revision = "0017_library_lifecycle"
down_revision = "0016_director_visual_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("projects", "brand_folders"):
        for name in ("archived", "deleted"):
            op.add_column(
                table, sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    for table in ("projects", "brand_folders"):
        op.drop_column(table, "deleted")
        op.drop_column(table, "archived")
