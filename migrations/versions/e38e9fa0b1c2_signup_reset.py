"""login_tokens.purpose and .password_hash, user_sessions.reset_until: sign-up with a password, password reset

Revision ID: e38e9fa0b1c2
Revises: d27d8e9fa0b1
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "e38e9fa0b1c2"
down_revision = "d27d8e9fa0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("login_tokens", sa.Column("purpose", sa.String(10), nullable=False, server_default="login"))
    op.add_column("login_tokens", sa.Column("password_hash", sa.String(200), nullable=True))
    op.add_column("user_sessions", sa.Column("reset_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_sessions", "reset_until")
    op.drop_column("login_tokens", "password_hash")
    op.drop_column("login_tokens", "purpose")
