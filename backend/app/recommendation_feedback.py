from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    DiscoveryCandidate,
    MediaItem,
    RecommendationOutcome,
    RecommendationSession,
)
from .schemas import (
    RecommendationEvaluationOut,
    RecommendationFeedbackRequest,
)


ALLOWED_ACTIONS = {
    "impression",
    "opened_details",
    "opened_watch_link",
    "selected",
    "added",
    "watched",
    "liked",
    "disliked",
    "skipped",
    "not_tonight",
    "not_interested",
    "already_watched",
    "too_long",
    "wrong_mood",
    "seen_similar_recently",
    "more_like_this",
    "less_like_this",
    "dismissed",
}


def _result_contains(
    recommendation_session: RecommendationSession,
    *,
    source: str,
    media_item_id: int | None,
    candidate: DiscoveryCandidate | None,
) -> bool:
    try:
        stored = json.loads(recommendation_session.results_json)
    except (TypeError, json.JSONDecodeError):
        return False
    if isinstance(stored, dict):
        stored = stored.get(source, [])
    if not isinstance(stored, list):
        return False
    if source == "local":
        return any(
            isinstance(result, dict) and result.get("title_id") == media_item_id
            for result in stored
        )
    if candidate is None:
        return False
    return any(
        isinstance(result, dict)
        and (
            result.get("candidate_id") == candidate.id
            or (
                result.get("tmdb_id") == candidate.tmdb_id
                and result.get("media_type") == candidate.media_type
            )
        )
        for result in stored
    )


def record_recommendation_feedback(
    session: Session,
    request: RecommendationFeedbackRequest,
) -> tuple[RecommendationOutcome, bool]:
    recommendation_session = session.get(RecommendationSession, request.session_id)
    if recommendation_session is None:
        raise LookupError("Recommendation session not found")
    if request.source not in {"local", "internet"}:
        raise ValueError("Invalid recommendation source")
    if request.action not in ALLOWED_ACTIONS:
        raise ValueError("Invalid recommendation action")
    candidate: DiscoveryCandidate | None = None
    if request.source == "local":
        if request.media_item_id is None or session.get(MediaItem, request.media_item_id) is None:
            raise LookupError("Recommended local title not found")
        candidate_id = None
        media_item_id = request.media_item_id
    else:
        candidate = (
            session.get(DiscoveryCandidate, request.candidate_id)
            if request.candidate_id is not None
            else None
        )
        if candidate is None:
            raise LookupError("Recommended internet candidate not found")
        candidate_id = candidate.id
        media_item_id = request.media_item_id
    if not _result_contains(
        recommendation_session,
        source=request.source,
        media_item_id=media_item_id,
        candidate=candidate,
    ):
        raise ValueError("Feedback target was not part of this recommendation session")

    existing = session.scalar(
        select(RecommendationOutcome).where(
            RecommendationOutcome.recommendation_session_id == request.session_id,
            RecommendationOutcome.source == request.source,
            RecommendationOutcome.action == request.action,
            RecommendationOutcome.media_item_id == media_item_id,
            RecommendationOutcome.discovery_candidate_id == candidate_id,
        )
    )
    if existing is not None:
        return existing, False
    outcome = RecommendationOutcome(
        recommendation_session_id=request.session_id,
        source=request.source,
        action=request.action,
        media_item_id=media_item_id,
        discovery_candidate_id=candidate_id,
    )
    session.add(outcome)
    session.commit()
    session.refresh(outcome)
    return outcome, True


def recommendation_evaluation(session: Session) -> RecommendationEvaluationOut:
    sessions = list(session.scalars(select(RecommendationSession)))
    agent_sessions = [record for record in sessions if record.mode == "agent"]
    gemini_sessions = 0
    for record in agent_sessions:
        try:
            snapshot = json.loads(record.taste_profile_snapshot_json)
        except (TypeError, json.JSONDecodeError):
            snapshot = {}
        if snapshot.get("provider") == "gemini":
            gemini_sessions += 1
    action_counts = dict(
        session.execute(
            select(RecommendationOutcome.action, func.count(RecommendationOutcome.id))
            .group_by(RecommendationOutcome.action)
        ).all()
    )
    outcomes = sum(action_counts.values())
    added = action_counts.get("added", 0)
    watched = action_counts.get("watched", 0)
    dismissed = action_counts.get("dismissed", 0)
    selected = action_counts.get("selected", 0)
    liked = action_counts.get("liked", 0)
    disliked = action_counts.get("disliked", 0)
    skipped = (
        action_counts.get("skipped", 0)
        + action_counts.get("not_tonight", 0)
        + action_counts.get("too_long", 0)
        + action_counts.get("wrong_mood", 0)
        + action_counts.get("seen_similar_recently", 0)
        + action_counts.get("less_like_this", 0)
    )
    watch_link_opens = action_counts.get("opened_watch_link", 0)
    impressions = action_counts.get("impression", 0)
    decision_actions = (
        added
        + watched
        + selected
        + liked
        + disliked
        + skipped
        + dismissed
    )
    positive_actions = added + watched + selected + liked
    return RecommendationEvaluationOut(
        sessions=len(sessions),
        agent_sessions=len(agent_sessions),
        gemini_sessions=gemini_sessions,
        fallback_sessions=len(agent_sessions) - gemini_sessions,
        outcomes=outcomes,
        added=added,
        watched=watched,
        dismissed=dismissed,
        selected=selected,
        liked=liked,
        disliked=disliked,
        skipped=skipped,
        watch_link_opens=watch_link_opens,
        impressions=impressions,
        positive_outcome_rate=(
            round(positive_actions / decision_actions, 4)
            if decision_actions
            else 0
        ),
        selection_rate=round(selected / impressions, 4) if impressions else 0,
        satisfaction_rate=(
            round(liked / (liked + disliked), 4) if liked + disliked else 0
        ),
        skip_rate=round(skipped / impressions, 4) if impressions else 0,
        fallback_rate=(
            round((len(agent_sessions) - gemini_sessions) / len(agent_sessions), 4)
            if agent_sessions
            else 0
        ),
    )
