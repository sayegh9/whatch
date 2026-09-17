"""recommendation outcomes

Revision ID: 7b81d4a91f22
Revises: 64fa0b8e2d13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b81d4a91f22"
down_revision: Union[str, None] = "64fa0b8e2d13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "recommendation_session_id",
            sa.Integer(),
            sa.ForeignKey("recommendation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "discovery_candidate_id",
            sa.Integer(),
            sa.ForeignKey("discovery_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_recommendation_outcomes_recommendation_session_id",
        "recommendation_outcomes",
        ["recommendation_session_id"],
    )
    op.create_index(
        "ix_recommendation_outcomes_source",
        "recommendation_outcomes",
        ["source"],
    )
    op.create_index(
        "ix_recommendation_outcomes_action",
        "recommendation_outcomes",
        ["action"],
    )
    op.create_index(
        "ix_recommendation_outcomes_media_item_id",
        "recommendation_outcomes",
        ["media_item_id"],
    )
    op.create_index(
        "ix_recommendation_outcomes_discovery_candidate_id",
        "recommendation_outcomes",
        ["discovery_candidate_id"],
    )


def downgrade() -> None:
    op.drop_table("recommendation_outcomes")
