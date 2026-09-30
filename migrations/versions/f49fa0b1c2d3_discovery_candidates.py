"""discovery_candidates: boards and employers the weekly discovery has already checked

Revision ID: f49fa0b1c2d3
Revises: e38e9fa0b1c2
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "f49fa0b1c2d3"
down_revision = "e38e9fa0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_candidates",
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("key", sa.String(300), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("nl", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_discovery_candidates_checked_at", "discovery_candidates", ["checked_at"])


def downgrade() -> None:
    op.drop_index("ix_discovery_candidates_checked_at", table_name="discovery_candidates")
    op.drop_table("discovery_candidates")
