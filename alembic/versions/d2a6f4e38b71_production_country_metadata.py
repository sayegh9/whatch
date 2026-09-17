"""Add production-country metadata used by Tonight filters.

Revision ID: d2a6f4e38b71
Revises: b8c13a9e4f21
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2a6f4e38b71"
down_revision: Union[str, None] = "b8c13a9e4f21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _country_codes(payload: dict) -> list[str]:
    return [
        country["iso_3166_1"].upper()
        for country in payload.get("production_countries", [])
        if country.get("iso_3166_1")
    ]


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(
            sa.Column("production_countries_json", sa.Text(), nullable=False, server_default="[]")
        )
    with op.batch_alter_table("discovery_candidates") as batch:
        batch.add_column(
            sa.Column("production_countries_json", sa.Text(), nullable=False, server_default="[]")
        )

    connection = op.get_bind()
    snapshots = sa.table(
        "provider_snapshots",
        sa.column("media_item_id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column("cache_key", sa.String),
        sa.column("response_json", sa.Text),
    )
    media_items = sa.table(
        "media_items",
        sa.column("id", sa.Integer),
        sa.column("production_countries_json", sa.Text),
    )
    for media_item_id, response_json in connection.execute(
        sa.select(snapshots.c.media_item_id, snapshots.c.response_json).where(
            snapshots.c.provider == "tmdb",
            snapshots.c.cache_key.like("details:%"),
        )
    ):
        try:
            countries = _country_codes(json.loads(response_json))
        except (TypeError, json.JSONDecodeError):
            continue
        if countries:
            connection.execute(
                media_items.update()
                .where(media_items.c.id == media_item_id)
                .values(production_countries_json=json.dumps(countries))
            )

    discoveries = sa.table(
        "discovery_candidates",
        sa.column("id", sa.Integer),
        sa.column("provider_payload_json", sa.Text),
        sa.column("production_countries_json", sa.Text),
    )
    for candidate_id, provider_payload_json in connection.execute(
        sa.select(discoveries.c.id, discoveries.c.provider_payload_json)
    ):
        try:
            countries = _country_codes(json.loads(provider_payload_json).get("tmdb", {}))
        except (TypeError, json.JSONDecodeError):
            continue
        if countries:
            connection.execute(
                discoveries.update()
                .where(discoveries.c.id == candidate_id)
                .values(production_countries_json=json.dumps(countries))
            )


def downgrade() -> None:
    with op.batch_alter_table("discovery_candidates") as batch:
        batch.drop_column("production_countries_json")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("production_countries_json")
