from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .discovery import discover_internet
from .metadata import provider_clients
from .models import MediaItem, RecommendationSession
from .recommendations import recommend_local
from .schemas import (
    AgentRecommendationRequest,
    AgentRecommendationResponse,
    AgentSearchPlanOut,
    DiscoveryResultOut,
    InternetRecommendationResponse,
    LocalRecommendationRequest,
    LocalRecommendationResponse,
    RecommendationResultOut,
)


class AgentChoice(BaseModel):
    candidate_key: str
    reason: str = Field(min_length=1, max_length=240)
    tradeoff: str = Field(min_length=1, max_length=180)


class AgentJudgment(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    interpreted_preferences: list[str] = Field(default_factory=list, max_length=8)
    choices: list[AgentChoice] = Field(default_factory=list, max_length=50)


class DiscoverySearchPlan(BaseModel):
    strategy: str = Field(min_length=1, max_length=300)
    queries: list[str] = Field(default_factory=list, max_length=6)


@dataclass(frozen=True)
class CandidatePayload:
    key: str
    source: Literal["local", "internet"]
    title: str
    year: int | None
    runtime_minutes: int | None
    genres: list[str]
    imdb_rating: float | None
    rt_rating: float | None
    deterministic_score: float
    reasons: list[str]
    overview: str | None

    def compact(self) -> dict:
        return {
            "candidate_key": self.key,
            "source": self.source,
            "title": self.title,
            "year": self.year,
            "runtime_minutes": self.runtime_minutes,
            "genres": self.genres,
            "imdb_rating": self.imdb_rating,
            "rt_rating": self.rt_rating,
            "deterministic_score": self.deterministic_score,
            "existing_reasons": self.reasons,
            "overview": (self.overview or "")[:700],
        }


class AgentUnavailable(RuntimeError):
    pass


class RecommendationJudge(Protocol):
    async def judge(
        self,
        request: AgentRecommendationRequest,
        candidates: list[CandidatePayload],
    ) -> AgentJudgment: ...


class DiscoveryPlanner(Protocol):
    async def plan(self, request: AgentRecommendationRequest) -> DiscoverySearchPlan: ...


class GeminiAdkPlanner:
    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise AgentUnavailable("Gemini API key is not configured")
        model = Gemini(
            model=settings.gemini_model,
            client_kwargs={"api_key": settings.gemini_api_key},
        )
        self.agent = LlmAgent(
            name="whatch_discovery_planner",
            description="Plans focused TMDB title searches for a movie or TV request.",
            model=model,
            mode="chat",
            output_schema=DiscoverySearchPlan,
            instruction=(
                "Translate the user's soft mood into up to six concise title-search "
                "queries suitable for TMDB. Queries should be recognizable movie or TV "
                "titles, creators, franchises, or specific thematic phrases—not filter "
                "syntax. Use multiple angles and avoid near-duplicates. The application "
                "will execute, validate, deduplicate, filter, and rank all results. Do not "
                "claim that any title was found."
            ),
            generate_content_config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=900,
            ),
        )

    async def plan(self, request: AgentRecommendationRequest) -> DiscoverySearchPlan:
        runner = InMemoryRunner(agent=self.agent, app_name="whatch")
        user_id = "local-owner"
        session_id = str(uuid.uuid4())
        await runner.session_service.create_session(
            app_name="whatch",
            user_id=user_id,
            session_id=session_id,
        )
        prompt = json.dumps(
            {
                "mood": request.prompt,
                "media_type": request.media_type,
                "runtime_max": request.runtime_max,
                "imdb_min": request.imdb_min,
                "rt_min": request.rt_min,
                "genres": request.genres,
                "excluded_genres": request.excluded_genres,
                "genre_mode": request.genre_mode,
                "release_year_mode": request.release_year_mode,
                "release_year": request.release_year,
                "adventure": request.adventure,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        final_text: str | None = None
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                if not event.is_final_response() or not event.content:
                    continue
                final_text = "".join(
                    part.text or "" for part in event.content.parts or [] if part.text
                )
        finally:
            await runner.close()
        if not final_text:
            raise AgentUnavailable("Gemini returned no discovery plan")
        plan = DiscoverySearchPlan.model_validate_json(final_text)
        clean_queries: list[str] = []
        for query in plan.queries:
            normalized = " ".join(query.split())[:80]
            if normalized and normalized.casefold() not in {
                existing.casefold() for existing in clean_queries
            }:
                clean_queries.append(normalized)
        return plan.model_copy(update={"queries": clean_queries[:6]})


class GeminiAdkJudge:
    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise AgentUnavailable("Gemini API key is not configured")
        self.model_name = settings.gemini_model
        model = Gemini(
            model=settings.gemini_model,
            client_kwargs={"api_key": settings.gemini_api_key},
        )
        self.agent = LlmAgent(
            name="whatch_tonight_judge",
            description="Reranks a validated movie and TV shortlist for tonight.",
            model=model,
            mode="chat",
            output_schema=AgentJudgment,
            instruction=(
                "You are Whatch's final shortlist judge. The application supplies only "
                "validated candidates. Never invent, rename, or substitute a title. Select "
                "only candidate_key values present in the input. Hard constraints have "
                "already been enforced; infer soft mood preferences from the request. "
                "Prefer a useful mix over near-duplicates. Give concrete reasons grounded "
                "only in supplied metadata and one honest tradeoff per choice. Return up to "
                "result_limit choices for each source represented in the input."
            ),
            generate_content_config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=3000,
            ),
        )

    async def judge(
        self,
        request: AgentRecommendationRequest,
        candidates: list[CandidatePayload],
    ) -> AgentJudgment:
        runner = InMemoryRunner(agent=self.agent, app_name="whatch")
        user_id = "local-owner"
        session_id = str(uuid.uuid4())
        await runner.session_service.create_session(
            app_name="whatch",
            user_id=user_id,
            session_id=session_id,
        )
        prompt = json.dumps(
            {
                "request": {
                    "mood": request.prompt,
                    "media_type": request.media_type,
                    "runtime_max": request.runtime_max,
                    "imdb_min": request.imdb_min,
                    "rt_min": request.rt_min,
                    "genres": request.genres,
                    "excluded_genres": request.excluded_genres,
                    "genre_mode": request.genre_mode,
                    "release_year_mode": request.release_year_mode,
                    "release_year": request.release_year,
                    "adventure": request.adventure,
                    "result_limit": request.limit,
                },
                "candidates": [candidate.compact() for candidate in candidates],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        final_text: str | None = None
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            ):
                if not event.is_final_response() or not event.content:
                    continue
                final_text = "".join(
                    part.text or "" for part in event.content.parts or [] if part.text
                )
        finally:
            await runner.close()
        if not final_text:
            raise AgentUnavailable("Gemini returned no final recommendation")
        return AgentJudgment.model_validate_json(final_text)


def _base_request(
    request: AgentRecommendationRequest,
    *,
    candidate_limit: int,
) -> LocalRecommendationRequest:
    return LocalRecommendationRequest(
        prompt=request.prompt,
        media_type=request.media_type,
        runtime_max=request.runtime_max,
        imdb_min=request.imdb_min,
        rt_min=request.rt_min,
        genres=request.genres,
        excluded_genres=request.excluded_genres,
        genre_mode=request.genre_mode,
        release_year_mode=request.release_year_mode,
        release_year=request.release_year,
        language=request.language,
        production_country=request.production_country,
        seed_title_ids=request.seed_title_ids,
        adventure=request.adventure,
        tone=request.tone,
        pace=request.pace,
        company=request.company,
        strict_metadata=request.strict_metadata,
        limit=candidate_limit,
    )


def _candidate_pool_limit(result_limit: int) -> int:
    return min(25, max(10, result_limit * 3))


def _genres_allowed(genres: list[str], request: AgentRecommendationRequest) -> bool:
    candidate_genres = {genre.strip().casefold() for genre in genres if genre.strip()}
    excluded = {
        genre.strip().casefold() for genre in request.excluded_genres if genre.strip()
    }
    if candidate_genres.intersection(excluded):
        return False
    required = {genre.strip().casefold() for genre in request.genres if genre.strip()}
    return not (
        request.genre_mode == "require"
        and required
        and not candidate_genres.intersection(required)
    )


def _year_allowed(year: int | None, request: AgentRecommendationRequest) -> bool:
    if request.release_year is None or request.release_year_mode == "any":
        return True
    if year is None:
        return False
    if request.release_year_mode == "before":
        return year < request.release_year
    return year > request.release_year


def _enforce_hard_genre_constraints(
    response: LocalRecommendationResponse | InternetRecommendationResponse | None,
    request: AgentRecommendationRequest,
) -> LocalRecommendationResponse | InternetRecommendationResponse | None:
    """Fail closed before and after LLM ranking so hard constraints cannot regress."""
    if response is None:
        return None
    filtered = [
        result
        for result in response.results
        if _genres_allowed(result.genres, request) and _year_allowed(result.year, request)
    ]
    removed = len(response.results) - len(filtered)
    return response.model_copy(
        update={
            "results": filtered,
            "candidate_count": max(0, response.candidate_count - removed),
        }
    )


def _local_candidates(
    session: Session,
    response: LocalRecommendationResponse | None,
) -> list[CandidatePayload]:
    if response is None:
        return []
    ids = [result.title_id for result in response.results]
    overviews = {
        item.id: item.overview
        for item in session.scalars(select(MediaItem).where(MediaItem.id.in_(ids)))
    }
    return [
        CandidatePayload(
            key=f"local:{result.title_id}",
            source="local",
            title=result.title,
            year=result.year,
            runtime_minutes=result.runtime_minutes,
            genres=result.genres,
            imdb_rating=result.imdb_rating,
            rt_rating=result.rotten_tomatoes_rating,
            deterministic_score=result.score,
            reasons=result.reasons,
            overview=overviews.get(result.title_id),
        )
        for result in response.results
    ]


def _internet_candidates(
    response: InternetRecommendationResponse | None,
) -> list[CandidatePayload]:
    if response is None:
        return []
    return [
        CandidatePayload(
            key=f"internet:{result.media_type}:{result.tmdb_id}",
            source="internet",
            title=result.title,
            year=result.year,
            runtime_minutes=result.runtime_minutes,
            genres=result.genres,
            imdb_rating=result.imdb_rating,
            rt_rating=result.rotten_tomatoes_rating,
            deterministic_score=result.score,
            reasons=result.reasons,
            overview=result.overview,
        )
        for result in response.results
    ]


def _apply_local_judgment(
    response: LocalRecommendationResponse | None,
    judgment: AgentJudgment | None,
    limit: int,
) -> LocalRecommendationResponse | None:
    if response is None:
        return None
    by_key = {f"local:{result.title_id}": result for result in response.results}
    ranked: list[RecommendationResultOut] = []
    seen: set[str] = set()
    if judgment:
        for choice in judgment.choices:
            result = by_key.get(choice.candidate_key)
            if result is None or choice.candidate_key in seen:
                continue
            ranked.append(
                result.model_copy(
                    update={
                        "agent_reason": choice.reason,
                        "agent_tradeoff": choice.tradeoff,
                    }
                )
            )
            seen.add(choice.candidate_key)
    ranked.extend(
        result
        for key, result in by_key.items()
        if key not in seen
    )
    return response.model_copy(update={"results": ranked[:limit]})


def _apply_internet_judgment(
    response: InternetRecommendationResponse | None,
    judgment: AgentJudgment | None,
    limit: int,
) -> InternetRecommendationResponse | None:
    if response is None:
        return None
    by_key = {
        f"internet:{result.media_type}:{result.tmdb_id}": result
        for result in response.results
    }
    ranked: list[DiscoveryResultOut] = []
    seen: set[str] = set()
    if judgment:
        for choice in judgment.choices:
            result = by_key.get(choice.candidate_key)
            if result is None or choice.candidate_key in seen:
                continue
            ranked.append(
                result.model_copy(
                    update={
                        "agent_reason": choice.reason,
                        "agent_tradeoff": choice.tradeoff,
                    }
                )
            )
            seen.add(choice.candidate_key)
    ranked.extend(
        result
        for key, result in by_key.items()
        if key not in seen
    )
    return response.model_copy(update={"results": ranked[:limit]})


def _fallback_summary(request: AgentRecommendationRequest) -> str:
    scope = {
        "local": "your saved catalog",
        "internet": "new provider discoveries",
        "hybrid": "your catalog and new provider discoveries",
    }.get(request.scope, "the available candidates")
    return f"Deterministic ranking from {scope}, with all selected constraints enforced."


async def recommend_with_agent(
    session: Session,
    request: AgentRecommendationRequest,
    settings: Settings,
    *,
    judge: RecommendationJudge | None = None,
    planner: DiscoveryPlanner | None = None,
) -> AgentRecommendationResponse:
    if request.scope not in {"local", "internet", "hybrid"}:
        raise ValueError("Invalid recommendation scope")
    candidate_limit = _candidate_pool_limit(request.limit)
    base_request = _base_request(request, candidate_limit=candidate_limit)

    can_use_gemini = bool(
        request.cloud_consent
        and settings.gemini_enabled
        and settings.gemini_api_key
    )
    search_plan: AgentSearchPlanOut | None = None
    planning_warning: str | None = None
    search_queries: list[str] = []
    if request.scope in {"internet", "hybrid"} and can_use_gemini:
        try:
            active_planner = planner or GeminiAdkPlanner(settings)
            planned = await active_planner.plan(request)
            search_queries = planned.queries
            search_plan = AgentSearchPlanOut(
                strategy=planned.strategy,
                queries=planned.queries,
            )
        except Exception as exc:
            planning_warning = f"Search planning fallback: {str(exc)[:220]}"

    local_response = (
        recommend_local(session, base_request)
        if request.scope in {"local", "hybrid"}
        else None
    )
    internet_response = None
    if request.scope in {"internet", "hybrid"}:
        tmdb, omdb = provider_clients(settings)
        internet_response = discover_internet(
            session,
            base_request,
            tmdb,
            omdb,
            search_queries=search_queries,
        )

    local_response = _enforce_hard_genre_constraints(local_response, request)
    internet_response = _enforce_hard_genre_constraints(internet_response, request)

    candidates = [
        *_local_candidates(session, local_response),
        *_internet_candidates(internet_response),
    ]
    judgment: AgentJudgment | None = None
    fallback_reason: str | None = None
    provider = "deterministic"
    if not request.cloud_consent:
        fallback_reason = "Gemini was not selected for this request."
    elif not settings.gemini_enabled:
        fallback_reason = "Gemini reasoning is disabled in local configuration."
    elif not settings.gemini_api_key:
        fallback_reason = "Gemini API key is not configured."
    elif not candidates:
        fallback_reason = "No validated candidates were available for Gemini to judge."
    else:
        try:
            active_judge = judge or GeminiAdkJudge(settings)
            judgment = await active_judge.judge(request, candidates)
            valid_keys = {candidate.key for candidate in candidates}
            if not any(choice.candidate_key in valid_keys for choice in judgment.choices):
                raise AgentUnavailable("Gemini did not select a valid candidate")
            provider = "gemini"
        except Exception as exc:
            fallback_reason = f"Gemini fallback: {str(exc)[:240]}"

    local_response = _apply_local_judgment(local_response, judgment, request.limit)
    internet_response = _apply_internet_judgment(
        internet_response, judgment, request.limit
    )
    local_response = _enforce_hard_genre_constraints(local_response, request)
    internet_response = _enforce_hard_genre_constraints(internet_response, request)
    if planning_warning and fallback_reason is None:
        fallback_reason = planning_warning
    summary = judgment.summary if judgment else _fallback_summary(request)
    preferences = judgment.interpreted_preferences if judgment else []
    audit = RecommendationSession(
        mode="agent",
        prompt=request.prompt,
        criteria_json=json.dumps(request.model_dump(), separators=(",", ":")),
        taste_profile_snapshot_json=json.dumps(
            {"provider": provider, "model": settings.gemini_model if judgment else None},
            separators=(",", ":"),
        ),
        results_json=json.dumps(
            {
                "summary": summary,
                "local": (
                    [result.model_dump(mode="json") for result in local_response.results]
                    if local_response
                    else []
                ),
                "internet": (
                    [
                        result.model_dump(mode="json")
                        for result in internet_response.results
                    ]
                    if internet_response
                    else []
                ),
            },
            separators=(",", ":"),
        ),
        confidence=(
            "medium"
            if provider == "gemini"
            else (
                local_response.confidence
                if local_response is not None
                else internet_response.confidence
                if internet_response is not None
                else "low"
            )
        ),
        candidate_count=len(candidates),
    )
    session.add(audit)
    session.commit()
    return AgentRecommendationResponse(
        session_id=audit.id,
        provider=provider,
        model=settings.gemini_model if provider == "gemini" else None,
        summary=summary,
        interpreted_preferences=preferences,
        fallback_reason=fallback_reason,
        search_plan=search_plan,
        local=local_response,
        internet=internet_response,
    )
