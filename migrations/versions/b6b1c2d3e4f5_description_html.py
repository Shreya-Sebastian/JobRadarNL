"""postings.description_html: the description with its formatting, cleaned to an allowlist (radar/htmlclean.py)

NULL means not read since the column was added; "" means the source gives no formatted text.

Revision ID: b6b1c2d3e4f5
Revises: a5a0b1c2d3e4
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "b6b1c2d3e4f5"
down_revision = "a5a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("postings", sa.Column("description_html", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("postings", "description_html")
