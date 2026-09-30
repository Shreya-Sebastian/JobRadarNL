"""login_tokens.remember: the "keep me signed in" choice

Revision ID: c16c7d8e9fa0
Revises: b05b6c7d8e9f
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "c16c7d8e9fa0"
down_revision = "b05b6c7d8e9f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("login_tokens", sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("login_tokens", "remember")
