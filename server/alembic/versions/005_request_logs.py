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
    op.create_table(
        "request_logs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("radius_km", sa.Float, nullable=True),
        sa.Column("travel_mode", sa.String(50), nullable=True),
        sa.Column("response_code", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Float, nullable=False),
        sa.Column("session_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("request_logs_created_at_idx", "request_logs", ["created_at"])
    op.create_index("request_logs_session_id_idx", "request_logs", ["session_id"])
    op.create_index("request_logs_endpoint_idx", "request_logs", ["endpoint"])

    op.create_table(
        "coverage_gaps",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("gap_type", sa.String(30), nullable=False),
        sa.Column("radius_km", sa.Float, nullable=True),
        sa.Column("prayer", sa.String(20), nullable=True),
        sa.Column("session_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("coverage_gaps_created_at_idx", "coverage_gaps", ["created_at"])
    op.create_index("coverage_gaps_type_idx", "coverage_gaps", ["gap_type"])


def downgrade() -> None:
    op.drop_index("coverage_gaps_type_idx", table_name="coverage_gaps")
    op.drop_index("coverage_gaps_created_at_idx", table_name="coverage_gaps")
    op.drop_table("coverage_gaps")
    op.drop_index("request_logs_endpoint_idx", table_name="request_logs")
    op.drop_index("request_logs_session_id_idx", table_name="request_logs")
    op.drop_index("request_logs_created_at_idx", table_name="request_logs")
    op.drop_table("request_logs")
