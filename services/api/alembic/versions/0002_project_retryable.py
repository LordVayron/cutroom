"""Record whether a project failure can be retried."""

import sqlalchemy as sa

from alembic import op

revision = "0002_project_retryable"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("projects", "retryable")
