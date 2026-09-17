"""Add local recommendation persistence.

Revision ID: 2c61a89ef430
Revises: 9d784e1bf120
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2c61a89ef430"
down_revision: Union[str, None] = "9d784e1bf120"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taste_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("source_title_count", sa.Integer(), nullable=False),
        sa.Column("source_rating_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "recommendation_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("prompt", sa.Text()),
        sa.Column("criteria_json", sa.Text(), nullable=False),
        sa.Column("taste_profile_snapshot_json", sa.Text(), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recommendation_sessions_mode", "recommendation_sessions", ["mode"])
    op.create_table(
        "dismissed_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("media_item_id"),
    )
    op.create_index(
        "ix_dismissed_recommendations_media_item_id",
        "dismissed_recommendations",
        ["media_item_id"],
    )


def downgrade() -> None:
    op.drop_table("dismissed_recommendations")
    op.drop_table("recommendation_sessions")
    op.drop_table("taste_profiles")
