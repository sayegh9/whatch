"""Add internet discovery persistence.

Revision ID: 64fa0b8e2d13
Revises: 2c61a89ef430
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "64fa0b8e2d13"
down_revision: Union[str, None] = "2c61a89ef430"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("imdb_id", sa.String(length=20)),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_title", sa.String(length=500)),
        sa.Column("release_date", sa.String(length=10)),
        sa.Column("runtime_minutes", sa.Integer()),
        sa.Column("genres_json", sa.Text(), nullable=False),
        sa.Column("overview", sa.Text()),
        sa.Column("poster_url", sa.Text()),
        sa.Column("original_language", sa.String(length=20)),
        sa.Column("imdb_rating", sa.Float()),
        sa.Column("rotten_tomatoes_rating", sa.Float()),
        sa.Column("tmdb_vote_average", sa.Float()),
        sa.Column("tmdb_vote_count", sa.Integer()),
        sa.Column("provider_payload_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tmdb_id", "media_type"),
    )
    op.create_index("ix_discovery_candidates_tmdb_id", "discovery_candidates", ["tmdb_id"])
    op.create_index("ix_discovery_candidates_media_type", "discovery_candidates", ["media_type"])
    op.create_index("ix_discovery_candidates_imdb_id", "discovery_candidates", ["imdb_id"])
    op.create_index("ix_discovery_candidates_title", "discovery_candidates", ["title"])
    op.create_index("ix_discovery_candidates_expires_at", "discovery_candidates", ["expires_at"])
    op.create_table(
        "dismissed_discoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tmdb_id", "media_type"),
    )
    op.create_index("ix_dismissed_discoveries_tmdb_id", "dismissed_discoveries", ["tmdb_id"])


def downgrade() -> None:
    op.drop_table("dismissed_discoveries")
    op.drop_table("discovery_candidates")
