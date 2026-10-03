"""employers: the sector of every employer on the radar (radar/sectors.py)

Revision ID: c7c2d3e4f5a6
Revises: b6b1c2d3e4f5
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "c7c2d3e4f5a6"
down_revision = "b6b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employers",
        sa.Column("company", sa.String(200), primary_key=True),
        sa.Column("sector", sa.String(30), nullable=False, server_default="other"),
        sa.Column("sector_source", sa.String(20), nullable=False, server_default="none"),
    )


def downgrade() -> None:
    op.drop_table("employers")
