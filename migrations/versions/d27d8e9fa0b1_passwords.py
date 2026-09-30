"""users.password_hash and users.password_set_at: optional passwords

Revision ID: d27d8e9fa0b1
Revises: c16c7d8e9fa0
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "d27d8e9fa0b1"
down_revision = "c16c7d8e9fa0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("password_set_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_set_at")
    op.drop_column("users", "password_hash")
