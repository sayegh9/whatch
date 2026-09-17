from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.metadata import (
    ProviderError,
    enqueue_metadata_backfill,
    metadata_readiness,
    refresh_item,
    set_manual_override,
)
from backend.app.models import MediaItem, MetadataJob, UserMediaState


class FakeTmdb:
    def find_by_imdb(self, imdb_id: str):
        assert imdb_id == "tt0095016"
        return {"movie_results": [{"id": 562}], "tv_results": []}

    def details(self, media_type: str, tmdb_id: int):
        assert (media_type, tmdb_id) == ("movie", 562)
        return {
            "id": 562,
            "title": "Die Hard (provider)",
            "original_title": "Die Hard",
            "release_date": "1988-07-15",
            "runtime": 132,
            "overview": "A New York cop faces a skyscraper hostage crisis.",
            "genres": [{"id": 28, "name": "Action"}, {"id": 53, "name": "Thriller"}],
            "original_language": "en",
            "poster_path": "/poster.jpg",
            "vote_average": 7.8,
            "vote_count": 11000,
        }

    def search(self, media_type: str, query: str, year: int | None):
        return {"results": []}


class FakeOmdb:
    def by_imdb(self, imdb_id: str):
        assert imdb_id == "tt0095016"
        return {
            "Response": "True",
            "imdbRating": "8.2",
            "Metascore": "72",
            "Ratings": [{"Source": "Rotten Tomatoes", "Value": "94%"}],
        }


class CountingTmdb(FakeTmdb):
    def __init__(self):
        self.find_calls = 0
        self.detail_calls = 0

    def find_by_imdb(self, imdb_id: str):
        self.find_calls += 1
        return super().find_by_imdb(imdb_id)

    def details(self, media_type: str, tmdb_id: int):
        self.detail_calls += 1
        return super().details(media_type, tmdb_id)


class CountingOmdb(FakeOmdb):
    def __init__(self):
        self.calls = 0

    def by_imdb(self, imdb_id: str):
        self.calls += 1
        return super().by_imdb(imdb_id)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_refresh_uses_exact_imdb_identity_and_preserves_manual_fields(session: Session):
    item = MediaItem(
        title="My preferred title",
        normalized_title="my preferred title",
        media_type="movie",
        imdb_id="tt0095016",
    )
    item.user_state = UserMediaState()
    session.add(item)
    session.flush()
    set_manual_override(session, item, "title", item.title)
    job = MetadataJob(media_item=item)
    session.add(job)
    session.flush()

    refresh_item(session, item, job, FakeTmdb(), FakeOmdb())
    session.commit()

    assert item.title == "My preferred title"
    assert item.runtime_minutes == 132
    assert json.loads(item.genres_json) == ["Action", "Thriller"]
    assert item.imdb_rating == 8.2
    assert item.rotten_tomatoes_rating == 94
    assert item.metacritic_rating == 72
    assert item.tmdb_id == 562
    assert item.metadata_status == "enriched"
    assert job.status == "succeeded"
    assert len(item.provider_snapshots) == 3


def test_refresh_rejects_items_without_imdb_identity(session: Session):
    item = MediaItem(
        title="Ambiguous",
        normalized_title="ambiguous",
        media_type="movie",
    )
    item.user_state = UserMediaState()
    job = MetadataJob(media_item=item)
    session.add_all([item, job])
    session.flush()

    with pytest.raises(ProviderError, match="IMDb ID"):
        refresh_item(session, item, job, FakeTmdb(), FakeOmdb())


def test_second_refresh_uses_unexpired_provider_snapshots(session: Session):
    item = MediaItem(
        title="Die Hard",
        normalized_title="die hard",
        media_type="movie",
        imdb_id="tt0095016",
    )
    item.user_state = UserMediaState()
    first_job = MetadataJob(media_item=item)
    session.add_all([item, first_job])
    session.flush()
    tmdb = CountingTmdb()
    omdb = CountingOmdb()

    refresh_item(session, item, first_job, tmdb, omdb)
    session.commit()
    second_job = MetadataJob(media_item=item)
    session.add(second_job)
    session.flush()
    refresh_item(session, item, second_job, tmdb, omdb)
    session.commit()

    assert (tmdb.find_calls, tmdb.detail_calls, omdb.calls) == (1, 1, 1)
    assert second_job.status == "succeeded"
    assert len(item.provider_snapshots) == 3


def test_backfill_enqueues_only_unmatched_inactive_titles(session: Session):
    ready = MediaItem(
        title="Ready",
        normalized_title="ready",
        media_type="movie",
        imdb_id="tt0095016",
        metadata_status="matched",
    )
    ready.user_state = UserMediaState()
    enriched = MediaItem(
        title="Enriched",
        normalized_title="enriched",
        media_type="movie",
        imdb_id="tt0086879",
        metadata_status="enriched",
        overview="Done",
    )
    enriched.user_state = UserMediaState()
    active = MediaItem(
        title="Active",
        normalized_title="active",
        media_type="movie",
        imdb_id="tt0111161",
        metadata_status="matched",
    )
    active.user_state = UserMediaState()
    active.metadata_jobs.append(MetadataJob(status="queued"))
    session.add_all([ready, enriched, active])
    session.commit()

    job_ids = enqueue_metadata_backfill(session, 10)
    readiness = metadata_readiness(session)

    assert len(job_ids) == 1
    assert session.get(MetadataJob, job_ids[0]).media_item_id == ready.id
    assert readiness["total"] == 3
    assert readiness["enriched"] == 1
    assert readiness["queued"] == 2
