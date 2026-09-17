from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.agent_recommendations import (
    AgentChoice,
    AgentJudgment,
    CandidatePayload,
    GeminiAdkJudge,
    recommend_with_agent,
)
from backend.app.config import Settings
from backend.app.database import Base
from backend.app.models import MediaItem, UserMediaState
from backend.app.schemas import AgentRecommendationRequest


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def settings(*, enabled: bool = True, key: str | None = "test-key") -> Settings:
    return Settings(
        database_url="sqlite://",
        catalog_source=Path("catalog.md"),
        tmdb_api_token=None,
        omdb_api_key=None,
        gemini_api_key=key,
        gemini_enabled=enabled,
        gemini_model="gemini-test",
        poster_directory=Path("posters"),
    )


def add_title(
    session: Session,
    title: str,
    rating: float,
    genres: list[str] | None = None,
) -> MediaItem:
    item = MediaItem(
        title=title,
        normalized_title=title.casefold(),
        media_type="movie",
        start_year=2024,
        runtime_minutes=100,
        imdb_rating=rating,
        rotten_tomatoes_rating=80,
        overview=f"{title} is a thoughtful mystery.",
        genres_json=json.dumps(genres or ["Mystery", "Drama"]),
    )
    item.user_state = UserMediaState(status="want_to_watch", priority="normal")
    session.add(item)
    session.flush()
    return item


class FakeJudge:
    def __init__(self) -> None:
        self.candidates: list[CandidatePayload] = []

    async def judge(
        self,
        request: AgentRecommendationRequest,
        candidates: list[CandidatePayload],
    ) -> AgentJudgment:
        self.candidates = candidates
        selected = next(candidate for candidate in candidates if candidate.title == "Second")
        return AgentJudgment(
            summary="Second best matches the requested low-key mystery mood.",
            interpreted_preferences=["low-key", "mystery"],
            choices=[
                AgentChoice(
                    candidate_key=selected.key,
                    reason="The supplied overview and genres best match a low-key mystery.",
                    tradeoff="Its audience rating is slightly lower.",
                )
            ],
        )


def test_agent_reranks_only_validated_candidates_and_attaches_explanation():
    with make_session() as session:
        add_title(session, "First", 8.5)
        second = add_title(session, "Second", 7.5)
        session.commit()
        judge = FakeJudge()

        response = asyncio.run(
            recommend_with_agent(
                session,
                AgentRecommendationRequest(
                    prompt="a low-key mystery",
                    scope="local",
                    cloud_consent=True,
                    limit=2,
                ),
                settings(),
                judge=judge,
            )
        )

        assert response.provider == "gemini"
        assert response.local is not None
        assert response.local.results[0].title_id == second.id
        assert response.local.results[0].agent_reason is not None
        assert response.local.results[0].agent_tradeoff is not None
        assert {candidate.title for candidate in judge.candidates} == {"First", "Second"}
        assert response.interpreted_preferences == ["low-key", "mystery"]


class FailingIfCalledJudge:
    async def judge(
        self,
        request: AgentRecommendationRequest,
        candidates: list[CandidatePayload],
    ) -> AgentJudgment:
        raise AssertionError("judge must not be called without cloud consent")


def test_agent_falls_back_locally_without_per_request_cloud_consent():
    with make_session() as session:
        add_title(session, "Local Only", 8.0)
        session.commit()

        response = asyncio.run(
            recommend_with_agent(
                session,
                AgentRecommendationRequest(
                    scope="local",
                    cloud_consent=False,
                    limit=1,
                ),
                settings(),
                judge=FailingIfCalledJudge(),
            )
        )

        assert response.provider == "deterministic"
        assert response.model is None
        assert response.fallback_reason == "Gemini was not selected for this request."
        assert response.local is not None
        assert [result.title for result in response.local.results] == ["Local Only"]


def test_agent_preserves_excluded_genres_before_gemini_and_load_more_ranking():
    with make_session() as session:
        animated = add_title(session, "Animated Candidate", 9.0, ["Animation", "Adventure"])
        animated.start_year = 1990
        allowed = add_title(session, "Second", 7.5, ["Mystery", "Drama"])
        allowed.start_year = 1994
        too_new = add_title(session, "Future Candidate", 8.5, ["Mystery", "Drama"])
        too_new.start_year = 2024
        session.commit()
        judge = FakeJudge()

        response = asyncio.run(
            recommend_with_agent(
                session,
                AgentRecommendationRequest(
                    scope="local",
                    cloud_consent=True,
                    excluded_genres=["animation", "documentary"],
                    release_year_mode="before",
                    release_year=2000,
                    limit=5,
                ),
                settings(),
                judge=judge,
            )
        )

        assert response.local is not None
        assert [result.title_id for result in response.local.results] == [allowed.id]
        assert [candidate.title for candidate in judge.candidates] == ["Second"]
        assert response.local.criteria["excluded_genres"] == [
            "animation",
            "documentary",
        ]
        assert response.local.criteria["release_year_mode"] == "before"
        assert response.local.criteria["release_year"] == 2000


def test_gemini_adk_root_agent_uses_chat_mode():
    judge = GeminiAdkJudge(settings())

    assert judge.agent.mode == "chat"
