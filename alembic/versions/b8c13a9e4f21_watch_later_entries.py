"""Add the durable Watch Later queue.

Revision ID: b8c13a9e4f21
Revises: 7b81d4a91f22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c13a9e4f21"
down_revision: Union[str, None] = "7b81d4a91f22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watch_later_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_watch_later_entries_media_item_id",
        "watch_later_entries",
        ["media_item_id"],
        unique=True,
    )
    op.create_index(
        "ix_watch_later_entries_added_at",
        "watch_later_entries",
        ["added_at"],
    )


def downgrade() -> None:
    op.drop_table("watch_later_entries")
