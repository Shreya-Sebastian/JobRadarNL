"""feedback: messages from the feedback page

Revision ID: a5a0b1c2d3e4
Revises: f49fa0b1c2d3
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "a5a0b1c2d3e4"
down_revision = "f49fa0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("page", sa.String(300), nullable=True),
        sa.Column("lang", sa.String(2), nullable=False, server_default="en"),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_table("feedback")
