"""posting.valid_through: the employer's own expiry date (schema.org validThrough)

Revision ID: 7c1d2e3f4a5b
Revises: 54fa914ff2c5
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "7c1d2e3f4a5b"
down_revision = "54fa914ff2c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("postings", sa.Column("valid_through", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("postings", "valid_through")
