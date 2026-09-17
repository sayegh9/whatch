from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.discovery import add_discovery_to_library, discover_internet
from backend.app.models import DiscoveryCandidate, MediaItem, UserMediaState
from backend.app.schemas import LocalRecommendationRequest


class FakeTmdb:
    def __init__(self):
        self.detail_calls = 0
        self.external_calls = 0
        self.find_calls = 0
        self.discover_calls = []

    def find_by_imdb(self, imdb_id: str):
        self.find_calls += 1
        return {
            "movie_results": [{"id": 100, "title": "Imported Seed"}],
            "tv_results": [],
        }

    def genre_list(self, media_type: str):
        return {"genres": [{"id": 53, "name": "Thriller"}]}

    def recommendations(self, media_type: str, tmdb_id: int):
        return {
            "results": [
                {
                    "id": 900,
                    "title": "New Online Film",
                    "overview": "A dark cerebral story about memory.",
                    "release_date": "2024-01-10",
                    "vote_average": 7.8,
                }
            ]
        }

    def discover(self, media_type: str, params):
        self.discover_calls.append(params)
        return {
            "results": [
                {
                    "id": 900,
                    "title": "New Online Film",
                    "overview": "A dark cerebral story about memory.",
                    "release_date": "2024-01-10",
                    "vote_average": 7.8,
                },
                {
                    "id": 100,
                    "title": "Local Seed",
                    "overview": "Already local.",
                    "release_date": "2020-01-01",
                    "vote_average": 8,
                },
            ]
        }

    def search(self, media_type: str, query: str, year: int | None):
        return {
            "results": [
                {
                    "id": 900,
                    "title": "New Online Film",
                    "overview": "A dark cerebral story about memory.",
                    "release_date": "2024-01-10",
                    "vote_average": 7.8,
                }
            ]
        }

    def details(self, media_type: str, tmdb_id: int):
        self.detail_calls += 1
        assert tmdb_id == 900
        return {
            "id": 900,
            "title": "New Online Film",
            "original_title": "New Online Film",
            "release_date": "2024-01-10",
            "runtime": 96,
            "genres": [{"id": 53, "name": "Thriller"}],
            "overview": "A dark cerebral story about memory.",
            "original_language": "en",
            "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
            "poster_path": "/new.jpg",
            "vote_average": 7.8,
            "vote_count": 500,
        }

    def external_ids(self, media_type: str, tmdb_id: int):
        self.external_calls += 1
        return {"imdb_id": "tt9999900"}


class FakeOmdb:
    def __init__(self):
        self.calls = 0

    def by_imdb(self, imdb_id: str):
        self.calls += 1
        return {
            "Response": "True",
            "imdbRating": "7.7",
            "Ratings": [{"Source": "Rotten Tomatoes", "Value": "91%"}],
        }


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_internet_discovery_excludes_local_titles_and_caches_candidates():
    with make_session() as session:
        local = MediaItem(
            title="Local Seed",
            normalized_title="local seed",
            media_type="movie",
            start_year=2020,
            tmdb_id=100,
            tmdb_media_type="movie",
            imdb_rating=8.0,
            metadata_status="enriched",
        )
        local.user_state = UserMediaState(status="watched", user_rating=9)
        session.add(local)
        session.commit()
        tmdb = FakeTmdb()
        omdb = FakeOmdb()
        request = LocalRecommendationRequest(
            prompt="dark cerebral memory",
            media_type="movie",
            runtime_max=110,
            genres=["Thriller"],
            limit=5,
        )

        first = discover_internet(session, request, tmdb, omdb)
        second = discover_internet(session, request, tmdb, omdb)

        assert first.candidate_count == 1
        assert [result.title for result in first.results] == ["New Online Film"]
        assert first.results[0].runtime_minutes == 96
        assert first.results[0].rotten_tomatoes_rating == 91
        assert "Local Seed" in first.results[0].seed_titles
        assert second.results[0].candidate_id == first.results[0].candidate_id
        assert (tmdb.detail_calls, tmdb.external_calls, omdb.calls) == (1, 1, 1)


def test_internet_discovery_filters_language_and_production_country_at_provider_and_cache():
    with make_session() as session:
        local = MediaItem(
            title="Local Seed",
            normalized_title="local seed",
            media_type="movie",
            start_year=2020,
            tmdb_id=100,
            tmdb_media_type="movie",
        )
        local.user_state = UserMediaState(status="watched", user_rating=9)
        session.add(local)
        session.commit()
        tmdb = FakeTmdb()

        response = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie",
                language="EN",
                production_country="us",
            ),
            tmdb,
            FakeOmdb(),
        )

        assert [result.title for result in response.results] == ["New Online Film"]
        assert all(call["with_original_language"] == "en" for call in tmdb.discover_calls)
        assert all(call["with_origin_country"] == "US" for call in tmdb.discover_calls)
        assert response.results[0].original_language == "en"
        assert response.results[0].production_countries == ["US"]

        excluded = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie",
                language="fr",
                production_country="FR",
            ),
            tmdb,
            FakeOmdb(),
        )

        assert excluded.results == []


def test_discovery_candidate_can_be_added_to_local_library():
    with make_session() as session:
        local = MediaItem(
            title="Local Seed",
            normalized_title="local seed",
            media_type="movie",
            start_year=2020,
            tmdb_id=100,
            tmdb_media_type="movie",
            metadata_status="enriched",
        )
        local.user_state = UserMediaState(status="watched", user_rating=9)
        session.add(local)
        session.commit()
        tmdb = FakeTmdb()
        omdb = FakeOmdb()
        response = discover_internet(
            session,
            LocalRecommendationRequest(media_type="movie"),
            tmdb,
            omdb,
        )

        item, created = add_discovery_to_library(
            session, response.results[0].candidate_id
        )
        second_item, created_again = add_discovery_to_library(
            session, response.results[0].candidate_id
        )

        assert created is True
        assert created_again is False
        assert second_item.id == item.id
        assert item.user_state.status == "want_to_watch"
        assert item.links[0].domain == "themoviedb.org"
        assert session.scalar(select(DiscoveryCandidate)).imdb_id == "tt9999900"


def test_internet_discovery_executes_and_exposes_agent_search_queries():
    with make_session() as session:
        local = MediaItem(
            title="Local Seed",
            normalized_title="local seed",
            media_type="movie",
            start_year=2020,
            tmdb_id=100,
            tmdb_media_type="movie",
            metadata_status="enriched",
        )
        local.user_state = UserMediaState(status="watched", user_rating=9)
        session.add(local)
        session.commit()
        tmdb = FakeTmdb()
        response = discover_internet(
            session,
            LocalRecommendationRequest(
                prompt="dark cerebral memory",
                media_type="movie",
            ),
            tmdb,
            FakeOmdb(),
            search_queries=[" cerebral mystery ", "cerebral mystery"],
        )

        assert response.search_queries == ["cerebral mystery"]
        assert any(
            reason == "Found by agent search: cerebral mystery"
            for reason in response.results[0].reasons
        )


def test_internet_genre_preference_is_soft_and_required_mode_is_hard():
    with make_session() as session:
        local = MediaItem(
            title="Local Seed",
            normalized_title="local seed",
            media_type="movie",
            start_year=2020,
            tmdb_id=100,
            tmdb_media_type="movie",
        )
        local.user_state = UserMediaState(status="watched", user_rating=9)
        session.add(local)
        session.commit()
        tmdb = FakeTmdb()
        preferred = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie", genres=["Comedy"], genre_mode="prefer"
            ),
            tmdb,
            FakeOmdb(),
        )
        required = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie", genres=["Comedy"], genre_mode="require"
            ),
            tmdb,
            FakeOmdb(),
        )

        assert preferred.candidate_count == 1
        assert required.candidate_count == 0


def test_internet_release_year_constraint_filters_seed_and_discovery_candidates():
    with make_session() as session:
        local = MediaItem(
            title="Local Seed",
            normalized_title="local seed",
            media_type="movie",
            start_year=2020,
            tmdb_id=100,
            tmdb_media_type="movie",
        )
        local.user_state = UserMediaState(status="watched", user_rating=9)
        session.add(local)
        session.commit()

        included = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie", release_year_mode="after", release_year=2023
            ),
            FakeTmdb(),
            FakeOmdb(),
        )
        excluded = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie", release_year_mode="before", release_year=2024
            ),
            FakeTmdb(),
            FakeOmdb(),
        )

        assert [result.year for result in included.results] == [2024]
        assert excluded.results == []


def test_explicit_imdb_only_seed_resolves_tmdb_identity_without_taste_fallback():
    with make_session() as session:
        imported_seed = MediaItem(
            title="Imported Seed",
            normalized_title="imported seed",
            media_type="movie",
            start_year=2020,
            imdb_id="tt0000100",
            metadata_status="matched",
        )
        imported_seed.user_state = UserMediaState(status="want_to_watch")
        unrelated = MediaItem(
            title="Unrelated Taste Seed",
            normalized_title="unrelated taste seed",
            media_type="movie",
            start_year=2021,
            tmdb_id=777,
            tmdb_media_type="movie",
            metadata_status="enriched",
        )
        unrelated.user_state = UserMediaState(
            status="watched",
            user_rating=10,
        )
        session.add_all([imported_seed, unrelated])
        session.commit()
        tmdb = FakeTmdb()

        response = discover_internet(
            session,
            LocalRecommendationRequest(
                media_type="movie",
                seed_title_ids=[imported_seed.id],
            ),
            tmdb,
            FakeOmdb(),
        )

        assert tmdb.find_calls == 1
        assert response.results[0].seed_titles == ["Imported Seed"]
        assert "Unrelated Taste Seed" not in response.results[0].reasons[0]
