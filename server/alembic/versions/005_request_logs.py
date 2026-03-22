"""Add request_logs and coverage_gaps tables for tracking API usage and dashboard metrics

Revision ID: 005
Revises: 004
Create Date: 2026-03-21 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS to handle partially-applied state
    op.execute("""
        CREATE TABLE IF NOT EXISTS request_logs (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            endpoint VARCHAR(500) NOT NULL,
            method VARCHAR(10) NOT NULL,
            lat FLOAT,
            lng FLOAT,
            radius_km FLOAT,
            travel_mode VARCHAR(50),
            response_code INTEGER NOT NULL,
            latency_ms FLOAT NOT NULL,
            session_id VARCHAR(200),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS request_logs_created_at_idx ON request_logs (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS request_logs_session_id_idx ON request_logs (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS request_logs_endpoint_idx ON request_logs (endpoint)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS coverage_gaps (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            lat FLOAT NOT NULL,
            lng FLOAT NOT NULL,
            gap_type VARCHAR(30) NOT NULL,
            radius_km FLOAT,
            prayer VARCHAR(20),
            session_id VARCHAR(200),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS coverage_gaps_created_at_idx ON coverage_gaps (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS coverage_gaps_type_idx ON coverage_gaps (gap_type)")


def downgrade() -> None:
    op.drop_index("coverage_gaps_type_idx", table_name="coverage_gaps")
    op.drop_index("coverage_gaps_created_at_idx", table_name="coverage_gaps")
    op.drop_table("coverage_gaps")
    op.drop_index("request_logs_endpoint_idx", table_name="request_logs")
    op.drop_index("request_logs_session_id_idx", table_name="request_logs")
    op.drop_index("request_logs_created_at_idx", table_name="request_logs")
    op.drop_table("request_logs")
