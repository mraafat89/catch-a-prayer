"""Add ip_hash columns to prayer_spots and prayer_spot_verifications for abuse protection

Revision ID: 003
Revises: 002
Create Date: 2026-03-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Store sha256(client_ip) on submission for IP-based rate limiting
    op.add_column("prayer_spots",
        sa.Column("submitted_ip_hash", sa.String(64), nullable=True))

    # Store sha256(client_ip) on each verification for cross-session dedup
    op.add_column("prayer_spot_verifications",
        sa.Column("ip_hash", sa.String(64), nullable=True))

    # Index for fast IP-rate-limit and per-spot IP dedup lookups
    op.create_index(
        "spot_verifications_ip_hash_idx",
        "prayer_spot_verifications",
        ["spot_id", "ip_hash"],
    )
    op.create_index(
        "prayer_spots_ip_hash_idx",
        "prayer_spots",
        ["submitted_ip_hash"],
    )


def downgrade() -> None:
    op.drop_index("prayer_spots_ip_hash_idx", table_name="prayer_spots")
    op.drop_index("spot_verifications_ip_hash_idx", table_name="prayer_spot_verifications")
    op.drop_column("prayer_spot_verifications", "ip_hash")
    op.drop_column("prayer_spots", "submitted_ip_hash")
