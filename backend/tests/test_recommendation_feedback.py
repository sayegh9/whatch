from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    DiscoveryCandidate,
    MediaItem,
    RecommendationSession,
    UserMediaState,
)
from backend.app.recommendation_feedback import (
    recommendation_evaluation,
    record_recommendation_feedback,
)
from backend.app.schemas import RecommendationFeedbackRequest


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_feedback_is_idempotent_and_evaluation_reports_agent_outcomes():
    with make_session() as session:
        item = MediaItem(
            title="Local",
            normalized_title="local",
            media_type="movie",
        )
        item.user_state = UserMediaState(status="want_to_watch")
        recommendation = RecommendationSession(
            mode="agent",
            prompt="mystery",
            criteria_json="{}",
            taste_profile_snapshot_json=json.dumps({"provider": "gemini"}),
            results_json=json.dumps({"local": [{"title_id": 1}], "internet": []}),
            confidence="medium",
            candidate_count=10,
        )
        session.add_all([item, recommendation])
        session.commit()

        request = RecommendationFeedbackRequest(
            session_id=recommendation.id,
            source="local",
            action="watched",
            media_item_id=item.id,
        )
        first, first_recorded = record_recommendation_feedback(session, request)
        second, second_recorded = record_recommendation_feedback(session, request)
        metrics = recommendation_evaluation(session)

        assert first.id == second.id
        assert first_recorded is True
        assert second_recorded is False
        assert metrics.agent_sessions == 1
        assert metrics.gemini_sessions == 1
        assert metrics.watched == 1
        assert metrics.positive_outcome_rate == 1
        assert metrics.fallback_rate == 0


def test_internet_feedback_requires_a_real_discovery_candidate():
    with make_session() as session:
        recommendation = RecommendationSession(
            mode="internet",
            prompt=None,
            criteria_json="{}",
            taste_profile_snapshot_json="{}",
            results_json=json.dumps(
                [{"candidate_id": 1, "tmdb_id": 42, "media_type": "movie"}]
            ),
            confidence="low",
            candidate_count=0,
        )
        candidate = DiscoveryCandidate(
            tmdb_id=42,
            media_type="movie",
            title="Candidate",
            genres_json="[]",
            provider_payload_json="{}",
        )
        session.add_all([recommendation, candidate])
        session.commit()

        outcome, recorded = record_recommendation_feedback(
            session,
            RecommendationFeedbackRequest(
                session_id=recommendation.id,
                source="internet",
                action="dismissed",
                candidate_id=candidate.id,
            ),
        )

        assert recorded is True
        assert outcome.discovery_candidate_id == candidate.id


def test_richer_feedback_produces_decision_quality_metrics():
    with make_session() as session:
        item = MediaItem(
            title="Tonight Pick",
            normalized_title="tonight pick",
            media_type="movie",
        )
        item.user_state = UserMediaState(status="want_to_watch")
        recommendation = RecommendationSession(
            mode="local",
            prompt="light",
            criteria_json="{}",
            taste_profile_snapshot_json="{}",
            results_json=json.dumps([{"title_id": 1}]),
            confidence="medium",
            candidate_count=1,
        )
        session.add_all([item, recommendation])
        session.commit()

        for action in ("impression", "opened_watch_link", "selected", "liked"):
            record_recommendation_feedback(
                session,
                RecommendationFeedbackRequest(
                    session_id=recommendation.id,
                    source="local",
                    action=action,
                    media_item_id=item.id,
                ),
            )

        metrics = recommendation_evaluation(session)

        assert metrics.impressions == 1
        assert metrics.watch_link_opens == 1
        assert metrics.selected == 1
        assert metrics.liked == 1
        assert metrics.selection_rate == 1
        assert metrics.satisfaction_rate == 1


def test_contextual_skip_reasons_are_recorded_without_becoming_durable_dislikes():
    with make_session() as session:
        item = MediaItem(title="Long Tonight", normalized_title="long tonight", media_type="movie")
        item.user_state = UserMediaState(status="want_to_watch")
        recommendation = RecommendationSession(
            mode="local",
            prompt=None,
            criteria_json="{}",
            taste_profile_snapshot_json="{}",
            results_json=json.dumps([{"title_id": 1}]),
            confidence="low",
            candidate_count=1,
        )
        session.add_all([item, recommendation])
        session.commit()

        outcome, recorded = record_recommendation_feedback(
            session,
            RecommendationFeedbackRequest(
                session_id=recommendation.id,
                source="local",
                action="too_long",
                media_item_id=item.id,
            ),
        )

        assert recorded is True
        assert outcome.action == "too_long"
        assert recommendation_evaluation(session).skipped == 1
