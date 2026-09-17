"""Add metadata reconciliation persistence.

Revision ID: 9d784e1bf120
Revises: 034e93b1bca8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d784e1bf120"
down_revision: Union[str, None] = "034e93b1bca8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column("release_date", sa.String(length=10), nullable=True))
        batch.add_column(
            sa.Column("genres_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("original_language", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("metacritic_rating", sa.Float(), nullable=True))
        batch.add_column(sa.Column("tmdb_vote_average", sa.Float(), nullable=True))
        batch.add_column(sa.Column("tmdb_vote_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("metadata_refreshed_at", sa.DateTime(timezone=True)))

    op.create_table(
        "provider_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("cache_key", sa.String(length=500), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_provider_snapshots_media_item_id", "provider_snapshots", ["media_item_id"])
    op.create_index("ix_provider_snapshots_provider", "provider_snapshots", ["provider"])
    op.create_index("ix_provider_snapshots_cache_key", "provider_snapshots", ["cache_key"])
    op.create_index("ix_provider_snapshots_expires_at", "provider_snapshots", ["expires_at"])

    op.create_table(
        "manual_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(length=80), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("media_item_id", "field_name"),
    )
    op.create_index("ix_manual_overrides_media_item_id", "manual_overrides", ["media_item_id"])

    op.create_table(
        "metadata_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
        ),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_metadata_jobs_media_item_id", "metadata_jobs", ["media_item_id"])
    op.create_index("ix_metadata_jobs_status", "metadata_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("metadata_jobs")
    op.drop_table("manual_overrides")
    op.drop_table("provider_snapshots")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("metadata_refreshed_at")
        batch.drop_column("tmdb_vote_count")
        batch.drop_column("tmdb_vote_average")
        batch.drop_column("metacritic_rating")
        batch.drop_column("original_language")
        batch.drop_column("genres_json")
        batch.drop_column("release_date")
