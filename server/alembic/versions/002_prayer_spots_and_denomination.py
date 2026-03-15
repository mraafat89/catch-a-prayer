"""Add prayer_spots, prayer_spot_verifications, and denomination tracking columns

Revision ID: 002
Revises: 001
Create Date: 2026-03-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New columns on mosques ---
    op.add_column("mosques", sa.Column("denomination_source", sa.String(30)))
    op.add_column("mosques", sa.Column("denomination_enriched_at", sa.DateTime(timezone=True)))

    # --- prayer_spots ---
    op.create_table(
        "prayer_spots",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("spot_type", sa.String(50), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("geom", geoalchemy2.Geometry(geometry_type="POINT", srid=4326)),
        sa.Column("address", sa.Text),
        sa.Column("city", sa.String(200)),
        sa.Column("state", sa.String(100)),
        sa.Column("zip", sa.String(20)),
        sa.Column("country", sa.String(2), nullable=False, server_default="US"),
        sa.Column("timezone", sa.String(100)),
        sa.Column("google_place_id", sa.String(200)),
        sa.Column("has_wudu_facilities", sa.Boolean),
        sa.Column("gender_access", sa.String(30), server_default="unknown"),
        sa.Column("is_indoor", sa.Boolean),
        sa.Column("operating_hours", sa.String(200)),
        sa.Column("notes", sa.Text),
        sa.Column("submitted_by_session", sa.String(200)),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("verification_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejection_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("prayer_spots_geom_idx", "prayer_spots", ["geom"], postgresql_using="gist")
    op.create_index("prayer_spots_status_idx", "prayer_spots", ["status"])
    op.create_index("prayer_spots_city_state_idx", "prayer_spots", ["city", "state"])

    # --- prayer_spot_verifications ---
    op.create_table(
        "prayer_spot_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "spot_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("prayer_spots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(200), nullable=False),
        sa.Column("is_positive", sa.Boolean, nullable=False),
        sa.Column("attributes", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("spot_id", "session_id", name="uq_spot_verification"),
    )
    op.create_index("spot_verifications_spot_idx", "prayer_spot_verifications", ["spot_id"])


def downgrade() -> None:
    op.drop_table("prayer_spot_verifications")
    op.drop_table("prayer_spots")
    op.drop_column("mosques", "denomination_enriched_at")
    op.drop_column("mosques", "denomination_source")
