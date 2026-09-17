from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaItem(Base):
    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    normalized_title: Mapped[str] = mapped_column(String(500), index=True)
    original_title: Mapped[str | None] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(20), index=True)
    start_year: Mapped[int | None] = mapped_column(Integer, index=True)
    end_year: Mapped[int | None] = mapped_column(Integer)
    is_ongoing: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    release_date: Mapped[str | None] = mapped_column(String(10))
    genres_json: Mapped[str] = mapped_column(Text, default="[]")
    original_language: Mapped[str | None] = mapped_column(String(20))
    production_countries_json: Mapped[str] = mapped_column(Text, default="[]")
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(Text)
    imdb_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    imdb_rating: Mapped[float | None] = mapped_column(Float, index=True)
    rotten_tomatoes_rating: Mapped[float | None] = mapped_column(Float, index=True)
    metacritic_rating: Mapped[float | None] = mapped_column(Float)
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    tmdb_media_type: Mapped[str | None] = mapped_column(String(20))
    tmdb_vote_average: Mapped[float | None] = mapped_column(Float)
    tmdb_vote_count: Mapped[int | None] = mapped_column(Integer)
    metadata_status: Mapped[str] = mapped_column(String(30), default="matched", index=True)
    metadata_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    links: Mapped[list["MediaLink"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )
    user_state: Mapped["UserMediaState"] = relationship(
        back_populates="media_item", cascade="all, delete-orphan", uselist=False
    )
    tags: Mapped[list["MediaTag"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )
    provider_snapshots: Mapped[list["ProviderSnapshot"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )
    manual_overrides: Mapped[list["ManualOverride"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )
    metadata_jobs: Mapped[list["MetadataJob"]] = relationship(
        back_populates="media_item", cascade="all, delete-orphan"
    )
    recommendation_dismissal: Mapped["DismissedRecommendation | None"] = relationship(
        back_populates="media_item", cascade="all, delete-orphan", uselist=False
    )
    watch_later_entry: Mapped["WatchLaterEntry | None"] = relationship(
        back_populates="media_item", cascade="all, delete-orphan", uselist=False
    )


class MediaLink(Base):
    __tablename__ = "media_links"
    __table_args__ = (UniqueConstraint("media_item_id", "url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    link_type: Mapped[str] = mapped_column(String(30), default="source")
    original_label: Mapped[str | None] = mapped_column(String(255))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media_item: Mapped[MediaItem] = relationship(back_populates="links")


class UserMediaState(Base):
    __tablename__ = "user_media_states"

    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(30), default="want_to_watch", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    user_rating: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    media_item: Mapped[MediaItem] = relationship(back_populates="user_state")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)


class MediaTag(Base):
    __tablename__ = "media_tags"
    __table_args__ = (UniqueConstraint("media_item_id", "tag_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))

    media_item: Mapped[MediaItem] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship()


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_path: Mapped[str] = mapped_column(Text)
    source_digest: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="preview")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    matched_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    review_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("import_job_id", "row_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    import_job_id: Mapped[int] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    raw_title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500), index=True)
    raw_year: Mapped[str | None] = mapped_column(String(50))
    raw_section: Mapped[str] = mapped_column(String(30))
    raw_url: Mapped[str | None] = mapped_column(Text)
    imdb_id: Mapped[str | None] = mapped_column(String(20), index=True)
    imdb_rating: Mapped[float | None] = mapped_column(Float)
    rt_rating: Mapped[float | None] = mapped_column(Float)
    match_status: Mapped[str] = mapped_column(String(100))
    proposed_action: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float, default=0)
    resolution_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    resolved_media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id", ondelete="SET NULL")
    )

    job: Mapped[ImportJob] = relationship(back_populates="rows")
    resolved_media_item: Mapped[MediaItem | None] = relationship()


class ProviderSnapshot(Base):
    __tablename__ = "provider_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20), index=True)
    cache_key: Mapped[str] = mapped_column(String(500), index=True)
    response_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    media_item: Mapped[MediaItem] = relationship(back_populates="provider_snapshots")


class ManualOverride(Base):
    __tablename__ = "manual_overrides"
    __table_args__ = (UniqueConstraint("media_item_id", "field_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(80))
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    media_item: Mapped[MediaItem] = relationship(back_populates="manual_overrides")


class MetadataJob(Base):
    __tablename__ = "metadata_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(40), default="refresh_item")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    media_item: Mapped[MediaItem | None] = relationship(back_populates="metadata_jobs")


class TasteProfile(Base):
    __tablename__ = "taste_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text)
    source_title_count: Mapped[int] = mapped_column(Integer, default=0)
    source_rating_count: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchLaterEntry(Base):
    __tablename__ = "watch_later_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    media_item: Mapped[MediaItem] = relationship(back_populates="watch_later_entry")


class RecommendationSession(Base):
    __tablename__ = "recommendation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="local", index=True)
    prompt: Mapped[str | None] = mapped_column(Text)
    criteria_json: Mapped[str] = mapped_column(Text)
    taste_profile_snapshot_json: Mapped[str] = mapped_column(Text)
    results_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecommendationOutcome(Base):
    __tablename__ = "recommendation_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_session_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_sessions.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id", ondelete="SET NULL"), index=True
    )
    discovery_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_candidates.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DismissedRecommendation(Base):
    __tablename__ = "dismissed_recommendations"
    __table_args__ = (UniqueConstraint("media_item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(40), default="not_interested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media_item: Mapped[MediaItem] = relationship(back_populates="recommendation_dismissal")


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (UniqueConstraint("tmdb_id", "media_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, index=True)
    media_type: Mapped[str] = mapped_column(String(20), index=True)
    imdb_id: Mapped[str | None] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    original_title: Mapped[str | None] = mapped_column(String(500))
    release_date: Mapped[str | None] = mapped_column(String(10))
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    genres_json: Mapped[str] = mapped_column(Text, default="[]")
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(Text)
    original_language: Mapped[str | None] = mapped_column(String(20))
    production_countries_json: Mapped[str] = mapped_column(Text, default="[]")
    imdb_rating: Mapped[float | None] = mapped_column(Float)
    rotten_tomatoes_rating: Mapped[float | None] = mapped_column(Float)
    tmdb_vote_average: Mapped[float | None] = mapped_column(Float)
    tmdb_vote_count: Mapped[int | None] = mapped_column(Integer)
    provider_payload_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class DismissedDiscovery(Base):
    __tablename__ = "dismissed_discoveries"
    __table_args__ = (UniqueConstraint("tmdb_id", "media_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, index=True)
    media_type: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(40), default="not_interested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
