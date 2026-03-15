"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # for fuzzy name search

    # mosques
    op.create_table(
        "mosques",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("name_arabic", sa.String(500)),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("geom", geoalchemy2.Geometry(geometry_type="POINT", srid=4326)),
        sa.Column("address", sa.Text),
        sa.Column("city", sa.String(200)),
        sa.Column("state", sa.String(100)),
        sa.Column("zip", sa.String(20)),
        sa.Column("country", sa.String(2), nullable=False, server_default="US"),
        sa.Column("timezone", sa.String(100)),
        sa.Column("phone", sa.String(50)),
        sa.Column("website", sa.String(1000)),
        sa.Column("email", sa.String(500)),
        sa.Column("osm_id", sa.String(50), unique=True),
        sa.Column("osm_type", sa.String(10)),
        sa.Column("google_place_id", sa.String(200), unique=True),
        sa.Column("islamicfinder_id", sa.String(100)),
        sa.Column("denomination", sa.String(100)),
        sa.Column("languages_spoken", postgresql.ARRAY(sa.String)),
        sa.Column("has_womens_section", sa.Boolean),
        sa.Column("has_parking", sa.Boolean),
        sa.Column("wheelchair_accessible", sa.Boolean),
        sa.Column("capacity", sa.Integer),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("places_enriched", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("mosques_geom_idx", "mosques", ["geom"], postgresql_using="gist")
    op.create_index("mosques_city_state_idx", "mosques", ["city", "state"])
    op.create_index("mosques_country_idx", "mosques", ["country"])
    op.create_index("mosques_active_idx", "mosques", ["is_active"])

    # prayer_schedules
    op.create_table(
        "prayer_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("mosque_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("fajr_adhan", sa.String(5)),
        sa.Column("fajr_iqama", sa.String(5)),
        sa.Column("fajr_adhan_source", sa.String(50)),
        sa.Column("fajr_iqama_source", sa.String(50)),
        sa.Column("fajr_adhan_confidence", sa.String(10)),
        sa.Column("fajr_iqama_confidence", sa.String(10)),
        sa.Column("sunrise", sa.String(5)),
        sa.Column("sunrise_source", sa.String(50)),
        sa.Column("dhuhr_adhan", sa.String(5)),
        sa.Column("dhuhr_iqama", sa.String(5)),
        sa.Column("dhuhr_adhan_source", sa.String(50)),
        sa.Column("dhuhr_iqama_source", sa.String(50)),
        sa.Column("dhuhr_adhan_confidence", sa.String(10)),
        sa.Column("dhuhr_iqama_confidence", sa.String(10)),
        sa.Column("asr_adhan", sa.String(5)),
        sa.Column("asr_iqama", sa.String(5)),
        sa.Column("asr_adhan_source", sa.String(50)),
        sa.Column("asr_iqama_source", sa.String(50)),
        sa.Column("asr_adhan_confidence", sa.String(10)),
        sa.Column("asr_iqama_confidence", sa.String(10)),
        sa.Column("maghrib_adhan", sa.String(5)),
        sa.Column("maghrib_iqama", sa.String(5)),
        sa.Column("maghrib_adhan_source", sa.String(50)),
        sa.Column("maghrib_iqama_source", sa.String(50)),
        sa.Column("maghrib_adhan_confidence", sa.String(10)),
        sa.Column("maghrib_iqama_confidence", sa.String(10)),
        sa.Column("isha_adhan", sa.String(5)),
        sa.Column("isha_iqama", sa.String(5)),
        sa.Column("isha_adhan_source", sa.String(50)),
        sa.Column("isha_iqama_source", sa.String(50)),
        sa.Column("isha_adhan_confidence", sa.String(10)),
        sa.Column("isha_iqama_confidence", sa.String(10)),
        sa.Column("scraped_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("mosque_id", "date", name="uq_prayer_schedule_mosque_date"),
    )
    op.create_index("prayer_schedules_mosque_date_idx", "prayer_schedules", ["mosque_id", "date"])
    op.create_index("prayer_schedules_date_idx", "prayer_schedules", ["date"])

    # jumuah_sessions
    op.create_table(
        "jumuah_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("mosque_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False),
        sa.Column("valid_date", sa.Date, nullable=False),
        sa.Column("session_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("khutba_start", sa.String(5)),
        sa.Column("prayer_start", sa.String(5)),
        sa.Column("imam_name", sa.String(200)),
        sa.Column("imam_title", sa.String(50)),
        sa.Column("imam_is_guest", sa.Boolean, server_default="false"),
        sa.Column("language", sa.String(100)),
        sa.Column("khutba_topic", sa.Text),
        sa.Column("khutba_series", sa.Text),
        sa.Column("capacity", sa.Integer),
        sa.Column("booking_required", sa.Boolean, server_default="false"),
        sa.Column("booking_url", sa.String(1000)),
        sa.Column("special_notes", sa.Text),
        sa.Column("source", sa.String(50)),
        sa.Column("confidence", sa.String(10)),
        sa.Column("scraped_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("mosque_id", "valid_date", "session_number", name="uq_jumuah_session"),
    )
    op.create_index("jumuah_sessions_mosque_date_idx", "jumuah_sessions", ["mosque_id", "valid_date"])
    op.create_index("jumuah_sessions_date_idx", "jumuah_sessions", ["valid_date"])

    # scraping_jobs
    op.create_table(
        "scraping_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("mosque_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("attempts_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tier_reached", sa.Integer),
        sa.Column("error_message", sa.Text),
        sa.Column("raw_html_url", sa.String(1000)),
        sa.Column("raw_extracted_json", postgresql.JSONB),
        sa.Column("image_urls_found", postgresql.ARRAY(sa.String)),
        sa.Column("dates_covered_from", sa.Date),
        sa.Column("dates_covered_until", sa.Date),
        sa.Column("scraped_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("scraping_jobs_status_next_idx", "scraping_jobs", ["status", "next_attempt_at"])
    op.create_index("scraping_jobs_priority_idx", "scraping_jobs", ["priority", "next_attempt_at"])

    # push_subscriptions
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("push_token", sa.Text, nullable=False, unique=True),
        sa.Column("push_platform", sa.String(20), nullable=False),
        sa.Column("vapid_endpoint", sa.Text),
        sa.Column("vapid_p256dh", sa.Text),
        sa.Column("vapid_auth", sa.Text),
        sa.Column("location_lat", sa.Float),
        sa.Column("location_lng", sa.Float),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("favorite_mosque_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("mosques.id", ondelete="SET NULL")),
        sa.Column("preferences", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_delivered_at", sa.DateTime(timezone=True)),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("push_subscriptions_active_idx", "push_subscriptions", ["is_active"])
    op.create_index("push_subscriptions_timezone_idx", "push_subscriptions", ["timezone"])


def downgrade() -> None:
    op.drop_table("push_subscriptions")
    op.drop_table("scraping_jobs")
    op.drop_table("jumuah_sessions")
    op.drop_table("prayer_schedules")
    op.drop_table("mosques")
    op.execute("DROP EXTENSION IF EXISTS postgis")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
