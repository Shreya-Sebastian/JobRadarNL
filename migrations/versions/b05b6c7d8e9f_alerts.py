"""users.alerts and users.alerts_sent_at: opt-in job alerts

Revision ID: b05b6c7d8e9f
Revises: af4a5b6c7d8e
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "b05b6c7d8e9f"
down_revision = "af4a5b6c7d8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("alerts", sa.String(10), nullable=False, server_default="off"))
    op.add_column("users", sa.Column("alerts_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "alerts_sent_at")
    op.drop_column("users", "alerts")
