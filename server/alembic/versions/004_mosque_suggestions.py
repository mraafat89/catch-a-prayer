"""Add mosque_suggestions and mosque_suggestion_votes tables for community corrections

Revision ID: 004
Revises: 003
Create Date: 2026-03-19 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mosque_suggestions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("mosque_id", UUID(as_uuid=False), sa.ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False),

        # What is being suggested
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("suggested_value", sa.Text, nullable=False),
        sa.Column("current_value", sa.Text, nullable=True),

        # Submission tracking (anonymous, same pattern as prayer_spots)
        sa.Column("submitted_by_session", sa.String(200), nullable=False),
        sa.Column("submitted_ip_hash", sa.String(64), nullable=True),

        # Community consensus
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("upvote_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("downvote_count", sa.Integer, nullable=False, server_default="0"),

        # Auto-expiry for time-sensitive data (iqama corrections)
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("mosque_suggestions_mosque_idx", "mosque_suggestions", ["mosque_id"])
    op.create_index("mosque_suggestions_status_idx", "mosque_suggestions", ["status"])
    op.create_index("mosque_suggestions_expires_idx", "mosque_suggestions", ["expires_at"],
                     postgresql_where=sa.text("status = 'pending'"))

    op.create_table(
        "mosque_suggestion_votes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("suggestion_id", UUID(as_uuid=False), sa.ForeignKey("mosque_suggestions.id", ondelete="CASCADE"), nullable=False),

        sa.Column("session_id", sa.String(200), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("is_positive", sa.Boolean, nullable=False),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.UniqueConstraint("suggestion_id", "session_id", name="uq_suggestion_vote_session"),
    )

    op.create_index("suggestion_votes_suggestion_idx", "mosque_suggestion_votes", ["suggestion_id"])
    op.create_index("suggestion_votes_ip_idx", "mosque_suggestion_votes", ["suggestion_id", "ip_hash"])


def downgrade() -> None:
    op.drop_index("suggestion_votes_ip_idx", table_name="mosque_suggestion_votes")
    op.drop_index("suggestion_votes_suggestion_idx", table_name="mosque_suggestion_votes")
    op.drop_table("mosque_suggestion_votes")
    op.drop_index("mosque_suggestions_expires_idx", table_name="mosque_suggestions")
    op.drop_index("mosque_suggestions_status_idx", table_name="mosque_suggestions")
    op.drop_index("mosque_suggestions_mosque_idx", table_name="mosque_suggestions")
    op.drop_table("mosque_suggestions")
