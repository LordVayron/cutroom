"""Add renewable leases for crash-safe worker jobs."""

import sqlalchemy as sa

from alembic import op

revision = "0003_job_leases"
down_revision = "0002_project_retryable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lock_token", sa.String(length=36), nullable=True))
    op.add_column(
        "jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "lock_token")
