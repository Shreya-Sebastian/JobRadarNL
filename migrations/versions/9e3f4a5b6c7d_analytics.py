"""analytics: anonymous page views and daily totals

Revision ID: 9e3f4a5b6c7d
Revises: 8d2e3f4a5b6c
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "9e3f4a5b6c7d"
down_revision = "8d2e3f4a5b6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("ms", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("referrer", sa.String(120)),
        sa.Column("utm_source", sa.String(60)),
        sa.Column("country", sa.String(2)),
        sa.Column("browser", sa.String(30)),
        sa.Column("os", sa.String(20)),
        sa.Column("device", sa.String(10)),
        sa.Column("bot", sa.Boolean(), nullable=False),
        sa.Column("visitor", sa.String(16)),
        sa.Column("event", sa.String(30)),
        sa.Column("detail", sa.String(200)),
    )
    op.create_index("ix_page_views_ts", "page_views", ["ts"])
    op.create_index("ix_page_views_visitor", "page_views", ["visitor"])
    op.create_table(
        "daily_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("dim", sa.String(20), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("humans", sa.Integer(), nullable=False),
        sa.Column("uniques", sa.Integer(), nullable=False),
        sa.UniqueConstraint("day", "dim", "key"),
    )
    op.create_index("ix_daily_stats_day", "daily_stats", ["day"])


def downgrade() -> None:
    op.drop_table("daily_stats")
    op.drop_table("page_views")
