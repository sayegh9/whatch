from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    DismissedRecommendation,
    MediaItem,
    MediaLink,
    RecommendationOutcome,
    RecommendationSession,
    UserMediaState,
)
from backend.app.recommendations import (
    SelectionFacets,
    derive_taste_profile,
    recommend_local,
    selection_similarity,
    semantic_cosines,
)
from backend.app.schemas import LocalRecommendationRequest


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_semantic_similarity_handles_titles_without_text() -> None:
    scores = semantic_cosines(["", "A tense crime drama"], "crime drama")

    assert scores[0] == 0.0
    assert scores[1] > scores[0]


def add_title(
    session: Session,
    title: str,
    *,
    runtime: int,
    imdb: float,
    rt: float,
    overview: str,
    genres: list[str],
    status: str = "want_to_watch",
    priority: str = "normal",
    language: str | None = None,
    production_countries: list[str] | None = None,
) -> MediaItem:
    item = MediaItem(
        title=title,
        normalized_title=title.casefold(),
        media_type="movie",
        runtime_minutes=runtime,
        imdb_rating=imdb,
        rotten_tomatoes_rating=rt,
        overview=overview,
        genres_json=json.dumps(genres),
        original_language=language,
        production_countries_json=json.dumps(production_countries or []),
    )
    item.user_state = UserMediaState(status=status, priority=priority)
    item.links.append(MediaLink(url=f"https://example.com/{title}", domain="example.com"))
    session.add(item)
    session.flush()
    return item


def test_selection_similarity_prioritizes_meaningful_facets_over_shared_filler_terms():
    reference = SelectionFacets(
        genres=frozenset({"drama", "mystery"}),
        terms=frozenset({"family", "secret", "returns", "home"}),
        decade=1990,
        language="en",
        countries=frozenset({"US"}),
    )
    same_story_shape = SelectionFacets(
        genres=frozenset({"drama", "mystery"}),
        terms=frozenset({"family", "secret", "returns", "village"}),
        decade=1990,
        language="en",
        countries=frozenset({"US"}),
    )
    genuinely_different = SelectionFacets(
        genres=frozenset({"animation", "adventure"}),
        terms=frozenset({"family", "journey", "ocean", "friendship"}),
        decade=2020,
        language="ja",
        countries=frozenset({"JP"}),
    )

    assert selection_similarity(reference, same_story_shape) > selection_similarity(
        reference, genuinely_different
    )


def test_local_recommendation_filters_language_and_production_country():
    with make_session() as session:
        matching = add_title(
            session,
            "Egyptian Drama",
            runtime=100,
            imdb=7.5,
            rt=80,
            overview="A family drama in Cairo.",
            genres=["Drama"],
            language="ar",
            production_countries=["EG"],
        )
        add_title(
            session,
            "American Drama",
            runtime=100,
            imdb=8.5,
            rt=90,
            overview="A family drama in New York.",
            genres=["Drama"],
            language="en",
            production_countries=["US"],
        )
        session.commit()

        response = recommend_local(
            session,
            LocalRecommendationRequest(language="AR", production_country="eg"),
        )

        assert [result.title_id for result in response.results] == [matching.id]
        assert response.criteria["language"] == "ar"
        assert response.criteria["production_country"] == "EG"


def test_local_recommendation_filters_and_explains_results():
    with make_session() as session:
        cerebral = add_title(
            session,
            "Short Cerebral Film",
            runtime=92,
            imdb=8.1,
            rt=95,
            overview="A dark cerebral story about identity and memory.",
            genres=["Thriller"],
            priority="high",
        )
        add_title(
            session,
            "Long Comedy",
            runtime=180,
            imdb=9.0,
            rt=99,
            overview="A broad sunny comedy.",
            genres=["Comedy"],
        )
        add_title(
            session,
            "Already Watched",
            runtime=90,
            imdb=9.2,
            rt=99,
            overview="A dark cerebral masterpiece.",
            genres=["Thriller"],
            status="watched",
        )
        session.commit()

        response = recommend_local(
            session,
            LocalRecommendationRequest(
                prompt="dark cerebral identity",
                runtime_max=100,
                imdb_min=7,
                limit=5,
            ),
        )

        assert response.candidate_count == 1
        assert [result.title_id for result in response.results] == [cerebral.id]
        assert response.results[0].links[0].domain == "example.com"
        assert response.results[0].score > 0
        assert response.results[0].score_breakdown["criteria_match"] > 0
        assert any("92 min" in reason for reason in response.results[0].reasons)
        assert response.confidence == "low"
        assert response.metadata_coverage == {
            "total": 3,
            "runtime": 3,
            "genres": 3,
            "overview": 3,
        }


def test_dismissed_title_is_removed_from_candidates():
    with make_session() as session:
        dismissed = add_title(
            session,
            "Dismissed",
            runtime=90,
            imdb=8,
            rt=90,
            overview="A film.",
            genres=["Drama"],
        )
        session.add(
            DismissedRecommendation(
                media_item=dismissed, reason="not_interested"
            )
        )
        session.commit()

        response = recommend_local(session, LocalRecommendationRequest())

        assert response.candidate_count == 0
        assert response.results == []


def test_local_recommendations_can_expand_beyond_initial_five():
    with make_session() as session:
        for index in range(15):
            add_title(
                session,
                f"Candidate {index:02d}",
                runtime=90 + index,
                imdb=7.0 + index / 100,
                rt=80 + index,
                overview="A thoughtful drama.",
                genres=["Drama"],
            )
        session.commit()

        response = recommend_local(
            session,
            LocalRecommendationRequest(limit=15),
        )

        assert response.candidate_count == 15
        assert len(response.results) == 15


def test_preferred_genres_are_soft_but_required_and_excluded_genres_are_hard():
    with make_session() as session:
        thriller = add_title(
            session,
            "Strong Thriller",
            runtime=100,
            imdb=8.2,
            rt=91,
            overview="A tense conspiracy thriller.",
            genres=["Thriller"],
        )
        comedy = add_title(
            session,
            "Strong Comedy",
            runtime=95,
            imdb=8.0,
            rt=90,
            overview="A warm workplace comedy.",
            genres=["Comedy"],
        )
        session.commit()

        preferred = recommend_local(
            session,
            LocalRecommendationRequest(genres=["Thriller"], genre_mode="prefer"),
        )
        required = recommend_local(
            session,
            LocalRecommendationRequest(genres=["Thriller"], genre_mode="require"),
        )
        excluded = recommend_local(
            session,
            LocalRecommendationRequest(excluded_genres=["Comedy"]),
        )

        assert {result.title_id for result in preferred.results} == {thriller.id, comedy.id}
        assert [result.title_id for result in required.results] == [thriller.id]
        assert [result.title_id for result in excluded.results] == [thriller.id]


def test_release_year_before_and_after_are_exclusive_hard_constraints():
    with make_session() as session:
        older = add_title(
            session,
            "Older Film",
            runtime=95,
            imdb=7.5,
            rt=80,
            overview="An older drama.",
            genres=["Drama"],
        )
        older.start_year = 1990
        boundary = add_title(
            session,
            "Boundary Film",
            runtime=95,
            imdb=7.5,
            rt=80,
            overview="A boundary-year drama.",
            genres=["Drama"],
        )
        boundary.start_year = 1995
        newer = add_title(
            session,
            "Newer Film",
            runtime=95,
            imdb=7.5,
            rt=80,
            overview="A newer drama.",
            genres=["Drama"],
        )
        newer.start_year = 2000
        session.commit()

        before = recommend_local(
            session,
            LocalRecommendationRequest(
                release_year_mode="before", release_year=1995
            ),
        )
        after = recommend_local(
            session,
            LocalRecommendationRequest(
                release_year_mode="after", release_year=1995
            ),
        )

        assert [result.title_id for result in before.results] == [older.id]
        assert [result.title_id for result in after.results] == [newer.id]
        assert boundary.id not in {
            *(result.title_id for result in before.results),
            *(result.title_id for result in after.results),
        }


def test_taste_profile_weights_high_ratings_and_tracks_low_rated_genres():
    with make_session() as session:
        loved = add_title(
            session,
            "Loved Science Fiction",
            runtime=100,
            imdb=8,
            rt=90,
            overview="A thoughtful space journey.",
            genres=["Science Fiction"],
            status="watched",
        )
        loved.user_state.user_rating = 10
        disliked = add_title(
            session,
            "Disliked Horror",
            runtime=95,
            imdb=7,
            rt=75,
            overview="A haunted house story.",
            genres=["Horror"],
            status="watched",
        )
        disliked.user_state.user_rating = 3
        session.commit()

        profile, taste_text, confidence = derive_taste_profile([loved, disliked])

        assert profile["liked_genres"] == ["science fiction"]
        assert profile["disliked_genres"] == ["horror"]
        assert profile["signal_weight"] == 1.25
        assert "thoughtful space journey" in taste_text.casefold()
        assert confidence == "low"


def test_selected_library_titles_anchor_similarity_and_are_not_returned():
    with make_session() as session:
        seed = add_title(
            session,
            "Selected Space Mystery",
            runtime=100,
            imdb=8.0,
            rt=90,
            overview="A cerebral space mystery around a distant signal.",
            genres=["Science Fiction", "Mystery"],
        )
        similar = add_title(
            session,
            "Another Space Mystery",
            runtime=105,
            imdb=7.5,
            rt=85,
            overview="A cerebral space mystery follows a strange distant signal.",
            genres=["Science Fiction", "Mystery"],
        )
        add_title(
            session,
            "Unrelated Comedy",
            runtime=95,
            imdb=8.5,
            rt=95,
            overview="A sunny workplace comedy.",
            genres=["Comedy"],
        )
        session.commit()

        response = recommend_local(
            session,
            LocalRecommendationRequest(seed_title_ids=[seed.id], limit=2),
        )

        assert seed.id not in [result.title_id for result in response.results]
        assert response.results[0].title_id == similar.id
        assert any(
            "selected library titles" in reason
            for reason in response.results[0].reasons
        )
        assert "anchored to 1 title" in response.confidence_reason


def test_context_uses_semantic_concepts_and_unknown_metadata_is_soft_by_default():
    with make_session() as session:
        uplifting = add_title(
            session,
            "Warm Choice",
            runtime=94,
            imdb=6.8,
            rt=72,
            overview="A charming uplifting story full of playful hope.",
            genres=["Drama"],
        )
        add_title(
            session,
            "Grim Choice",
            runtime=92,
            imdb=8.8,
            rt=96,
            overview="A bleak brooding noir tragedy.",
            genres=["Drama"],
        )
        unknown = MediaItem(
            title="Metadata Pending",
            normalized_title="metadata pending",
            media_type="movie",
            overview="A warm hopeful comedy.",
            genres_json=json.dumps(["Comedy"]),
        )
        unknown.user_state = UserMediaState(status="want_to_watch", priority="normal")
        session.add(unknown)
        session.commit()

        response = recommend_local(
            session,
            LocalRecommendationRequest(
                tone="light",
                runtime_max=120,
                imdb_min=6.5,
                limit=3,
            ),
        )
        strict = recommend_local(
            session,
            LocalRecommendationRequest(
                tone="light",
                runtime_max=120,
                imdb_min=6.5,
                strict_metadata=True,
                limit=3,
            ),
        )

        assert response.results[0].title_id == uplifting.id
        assert unknown.id in {result.title_id for result in response.results}
        assert unknown.id not in {result.title_id for result in strict.results}
        assert response.results[0].score_breakdown["semantic_similarity"] > 0


def test_explicit_feedback_changes_future_ranking():
    with make_session() as session:
        reference = add_title(
            session,
            "Liked Space Puzzle",
            runtime=100,
            imdb=7.5,
            rt=80,
            overview="A cerebral space mystery about identity and a distant signal.",
            genres=["Science Fiction", "Mystery"],
            status="watched",
        )
        similar = add_title(
            session,
            "Future Signal",
            runtime=100,
            imdb=7.0,
            rt=78,
            overview="A thoughtful mystery follows a signal through deep space.",
            genres=["Science Fiction", "Mystery"],
        )
        add_title(
            session,
            "Alphabetical Drama",
            runtime=100,
            imdb=7.0,
            rt=78,
            overview="A family drama in a small town.",
            genres=["Drama"],
        )
        recommendation = RecommendationSession(
            mode="local",
            prompt=None,
            criteria_json="{}",
            taste_profile_snapshot_json="{}",
            results_json=json.dumps([{"title_id": reference.id}]),
            confidence="low",
            candidate_count=1,
        )
        session.add(recommendation)
        session.flush()
        session.add(
            RecommendationOutcome(
                recommendation_session_id=recommendation.id,
                source="local",
                action="more_like_this",
                media_item_id=reference.id,
            )
        )
        session.commit()

        response = recommend_local(session, LocalRecommendationRequest(limit=2))

        assert response.results[0].title_id == similar.id
        assert response.results[0].score_breakdown["feedback_match"] > 0.05
