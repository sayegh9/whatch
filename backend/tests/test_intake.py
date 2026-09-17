from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.intake import commit_intake, parse_intake_input, resolve_intake
from backend.app.models import MediaItem, WatchLaterEntry
from backend.app.schemas import IntakeCommitRequest, IntakeResolveRequest


class FakeTmdb:
    def search(self, media_type: str, query: str, year: int | None):
        assert query == "Perfect Days"
        if media_type == "movie":
            return {
                "results": [{
                    "id": 976893,
                    "title": "Perfect Days",
                    "original_title": "PERFECT DAYS",
                    "release_date": "2023-11-10",
                    "overview": "A Tokyo cleaner finds beauty in ordinary life.",
                    "poster_path": "/perfect.jpg",
                    "vote_average": 7.8,
                    "vote_count": 1500,
                    "popularity": 30,
                }]
            }
        return {"results": []}

    def find_by_imdb(self, imdb_id: str):
        assert imdb_id == "tt27503384"
        return {"movie_results": [{"id": 976893}], "tv_results": []}

    def details(self, media_type: str, tmdb_id: int):
        assert media_type == "movie"
        assert tmdb_id == 976893
        return {
            "id": 976893,
            "title": "Perfect Days",
            "original_title": "PERFECT DAYS",
            "release_date": "2023-11-10",
            "runtime": 124,
            "overview": "A Tokyo cleaner finds beauty in ordinary life.",
            "genres": [{"name": "Drama"}],
            "poster_path": "/perfect.jpg",
            "original_language": "ja",
            "vote_average": 7.8,
            "vote_count": 1500,
        }

    def external_ids(self, media_type: str, tmdb_id: int):
        return {"imdb_id": "tt27503384"}


class FakeOmdb:
    def by_imdb(self, imdb_id: str):
        assert imdb_id == "tt27503384"
        return {
            "imdbRating": "7.9",
            "Metascore": "80",
            "Ratings": [{"Source": "Rotten Tomatoes", "Value": "96%"}],
        }


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def install_providers(monkeypatch):
    monkeypatch.setattr(
        "backend.app.intake.provider_clients",
        lambda _settings: (FakeTmdb(), FakeOmdb()),
    )


def test_resolve_accepts_names_and_exact_provider_links(monkeypatch):
    install_providers(monkeypatch)
    with make_session() as session:
        by_name = resolve_intake(
            session,
            IntakeResolveRequest(input="Perfect Days", media_type="either"),
        )
        by_imdb = resolve_intake(
            session,
            IntakeResolveRequest(
                input="https://www.imdb.com/title/tt27503384/",
                media_type="either",
            ),
        )

        assert by_name.input_kind == "title"
        assert by_name.exact is False
        assert by_name.candidates[0].title == "Perfect Days"
        assert by_imdb.input_kind == "imdb_url"
        assert by_imdb.exact is True
        assert by_imdb.candidates[0].tmdb_id == 976893


def test_commit_enriches_deduplicates_and_can_queue_watch_later(monkeypatch):
    install_providers(monkeypatch)
    with make_session() as session:
        request = IntakeCommitRequest(
            tmdb_id=976893,
            media_type="movie",
            destination="watch_later",
            source_url="https://www.imdb.com/title/tt27503384/",
        )
        first, created = commit_intake(session, request)
        second, created_again = commit_intake(session, request)

        assert created is True
        assert created_again is False
        assert first.id == second.id
        assert first.imdb_id == "tt27503384"
        assert first.imdb_rating == 7.9
        assert first.rotten_tomatoes_rating == 96
        assert first.runtime_minutes == 124
        assert first.poster_url.endswith("/perfect.jpg")
        assert session.scalar(select(func.count(MediaItem.id))) == 1
        assert session.scalar(select(func.count(WatchLaterEntry.id))) == 1


def test_unsupported_links_are_rejected_without_fetching():
    try:
        parse_intake_input("https://example.com/watch/perfect-days")
    except ValueError as exc:
        assert "Supported links" in str(exc)
    else:
        raise AssertionError("Unsupported links must not be accepted")
