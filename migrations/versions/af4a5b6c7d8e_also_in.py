"""postings.also_in: other cities of a vacancy listed once per city

Revision ID: af4a5b6c7d8e
Revises: 9e3f4a5b6c7d
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "af4a5b6c7d8e"
down_revision = "9e3f4a5b6c7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("postings", sa.Column("also_in", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("postings", "also_in")
