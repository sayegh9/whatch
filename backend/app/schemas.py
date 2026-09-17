from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LinkOut(BaseModel):
    id: int
    url: str
    domain: str
    link_type: str
    archived: bool

    model_config = ConfigDict(from_attributes=True)


class UserStateOut(BaseModel):
    status: str
    priority: str
    user_rating: float | None
    notes: str | None
    watched_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TitleSummary(BaseModel):
    id: int
    title: str
    media_type: str
    start_year: int | None
    end_year: int | None
    is_ongoing: bool
    imdb_id: str | None
    imdb_rating: float | None
    rotten_tomatoes_rating: float | None
    poster_url: str | None
    metadata_status: str
    status: str
    priority: str
    user_rating: float | None
    link_count: int
    tags: list[str]
    genres: list[str]
    watch_later: bool = False


class TitleDetail(TitleSummary):
    original_title: str | None
    runtime_minutes: int | None
    release_date: str | None
    genres: list[str]
    original_language: str | None
    overview: str | None
    metacritic_rating: float | None
    tmdb_vote_average: float | None
    tmdb_vote_count: int | None
    metadata_refreshed_at: datetime | None
    manual_fields: list[str]
    notes: str | None
    links: list[LinkOut]


class TitleListResponse(BaseModel):
    items: list[TitleSummary]
    total: int
    page: int
    page_size: int


class WatchLaterItemOut(TitleSummary):
    added_at: datetime


class WatchLaterResponse(BaseModel):
    items: list[WatchLaterItemOut]
    total: int


class WatchLaterMoveRequest(BaseModel):
    watched: bool = False


class TitlePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    original_title: str | None = Field(default=None, max_length=500)
    media_type: str | None = None
    start_year: int | None = Field(default=None, ge=1870, le=2200)
    end_year: int | None = Field(default=None, ge=1870, le=2200)
    is_ongoing: bool | None = None
    runtime_minutes: int | None = Field(default=None, ge=1, le=1440)
    overview: str | None = Field(default=None, max_length=20000)
    release_date: str | None = Field(default=None, max_length=10)
    poster_url: str | None = Field(default=None, max_length=4000)
    original_language: str | None = Field(default=None, max_length=20)
    imdb_rating: float | None = Field(default=None, ge=0, le=10)
    rotten_tomatoes_rating: float | None = Field(default=None, ge=0, le=100)
    metacritic_rating: float | None = Field(default=None, ge=0, le=100)
    genres: list[str] | None = None
    status: str | None = None
    priority: str | None = None
    user_rating: float | None = Field(default=None, ge=0, le=10)
    notes: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = None


class ImportRequest(BaseModel):
    source_path: str | None = None


class ImportStats(BaseModel):
    job_id: int
    total_rows: int
    matched_rows: int
    duplicate_rows: int
    review_rows: int
    canonical_candidates: int
    status: str


class ReviewRowOut(BaseModel):
    id: int
    raw_title: str
    raw_year: str | None
    raw_section: str
    raw_url: str | None
    match_status: str
    proposed_action: str
    confidence: float
    resolution_status: str

    model_config = ConfigDict(from_attributes=True)


class ReviewResolveRequest(BaseModel):
    action: str
    media_item_id: int | None = None
    title: str | None = None
    media_type: str | None = None
    start_year: int | None = None


class MetadataJobOut(BaseModel):
    id: int
    media_item_id: int | None
    job_type: str
    status: str
    attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MetadataReadinessOut(BaseModel):
    total: int
    eligible: int
    enriched: int
    runtime: int
    genres: int
    overview: int
    queued: int
    running: int
    failed: int


class MetadataBackfillRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=25)


class MetadataBackfillResponse(BaseModel):
    queued_job_ids: list[int]
    readiness: MetadataReadinessOut


class MetadataCandidate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    original_title: str | None
    release_date: str | None
    overview: str | None
    poster_url: str | None


class MetadataSearchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    media_type: str
    year: int | None = Field(default=None, ge=1870, le=2200)


class MetadataResolveRequest(BaseModel):
    tmdb_id: int = Field(gt=0)
    media_type: str


class IntakeResolveRequest(BaseModel):
    input: str = Field(min_length=1, max_length=2000)
    media_type: Literal["either", "movie", "tv"] = "either"


class IntakeCandidate(BaseModel):
    tmdb_id: int
    media_type: Literal["movie", "tv"]
    title: str
    original_title: str | None
    release_date: str | None
    overview: str | None
    poster_url: str | None
    tmdb_vote_average: float | None
    existing_media_item_id: int | None = None


class IntakeResolveResponse(BaseModel):
    input_kind: Literal["title", "imdb_url", "tmdb_url", "rt_url"]
    exact: bool
    normalized_input: str
    source_url: str | None = None
    candidates: list[IntakeCandidate]


class IntakeCommitRequest(BaseModel):
    tmdb_id: int = Field(gt=0)
    media_type: Literal["movie", "tv"]
    destination: Literal["library", "watch_later"]
    source_url: str | None = Field(default=None, max_length=2000)


class IntakeCommitResponse(BaseModel):
    item: TitleDetail
    created: bool
    destination: Literal["library", "watch_later"]


class LinkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    link_type: str = Field(default="source", max_length=30)
    original_label: str | None = Field(default=None, max_length=255)


class LocalRecommendationRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=1000)
    media_type: Literal["either", "movie", "tv"] = "either"
    runtime_max: int | None = Field(default=None, ge=20, le=600)
    imdb_min: float | None = Field(default=None, ge=0, le=10)
    rt_min: float | None = Field(default=None, ge=0, le=100)
    genres: list[str] = Field(default_factory=list, max_length=10)
    excluded_genres: list[str] = Field(default_factory=list, max_length=10)
    genre_mode: Literal["prefer", "require"] = "prefer"
    release_year_mode: Literal["any", "before", "after"] = "any"
    release_year: int | None = Field(default=None, ge=1888, le=2100)
    language: str | None = Field(default=None, max_length=3)
    production_country: str | None = Field(default=None, max_length=2)
    seed_title_ids: list[int] = Field(default_factory=list, max_length=20)
    adventure: Literal["safe", "adjacent", "adventurous"] = "adjacent"
    tone: Literal["any", "light", "balanced", "dark"] = "any"
    pace: Literal["any", "relaxed", "balanced", "fast"] = "any"
    company: Literal["any", "solo", "group"] = "any"
    strict_metadata: bool = False
    limit: int = Field(default=5, ge=1, le=25)

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("language must be a string code")
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if not normalized.isalpha() or len(normalized) not in {2, 3}:
            raise ValueError("language must be a 2- or 3-letter code")
        return normalized

    @field_validator("production_country", mode="before")
    @classmethod
    def normalize_production_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("production_country must be a string code")
        normalized = value.strip().upper()
        if not normalized:
            return None
        if not normalized.isalpha() or len(normalized) != 2:
            raise ValueError("production_country must be a 2-letter code")
        return normalized


class RecommendationLinkOut(BaseModel):
    url: str
    domain: str


class RecommendationResultOut(BaseModel):
    title_id: int
    title: str
    media_type: str
    year: int | None
    runtime_minutes: int | None
    genres: list[str]
    original_language: str | None = None
    production_countries: list[str] = Field(default_factory=list)
    poster_url: str | None
    imdb_id: str | None
    imdb_rating: float | None
    rotten_tomatoes_rating: float | None
    status: str
    priority: str
    watch_later: bool = False
    score: float
    score_breakdown: dict[str, float]
    reasons: list[str]
    links: list[RecommendationLinkOut]
    agent_reason: str | None = None
    agent_tradeoff: str | None = None


class LocalRecommendationResponse(BaseModel):
    session_id: int
    mode: str
    confidence: str
    confidence_reason: str
    candidate_count: int
    metadata_coverage: dict[str, int]
    criteria: dict
    results: list[RecommendationResultOut]


class DismissRecommendationRequest(BaseModel):
    reason: str = Field(default="not_interested", max_length=40)


class DiscoveryResultOut(BaseModel):
    candidate_id: int
    tmdb_id: int
    media_type: str
    imdb_id: str | None
    title: str
    year: int | None
    runtime_minutes: int | None
    genres: list[str]
    original_language: str | None = None
    production_countries: list[str] = Field(default_factory=list)
    overview: str | None
    poster_url: str | None
    imdb_rating: float | None
    rotten_tomatoes_rating: float | None
    tmdb_vote_average: float | None
    score: float
    score_breakdown: dict[str, float]
    reasons: list[str]
    seed_titles: list[str]
    tmdb_url: str
    agent_reason: str | None = None
    agent_tradeoff: str | None = None


class InternetRecommendationResponse(BaseModel):
    session_id: int
    mode: str
    confidence: str
    candidate_count: int
    criteria: dict
    results: list[DiscoveryResultOut]
    search_queries: list[str] = Field(default_factory=list)


class DiscoveryDismissRequest(BaseModel):
    reason: str = Field(default="not_interested", max_length=40)


class AddDiscoveryResponse(BaseModel):
    media_item_id: int
    created: bool


class AgentRecommendationRequest(LocalRecommendationRequest):
    scope: str = "local"
    cloud_consent: bool = False


class AgentStatusOut(BaseModel):
    available: bool
    enabled: bool
    configured: bool
    model: str
    privacy_summary: str


class AgentSearchPlanOut(BaseModel):
    strategy: str
    queries: list[str]


class AgentRecommendationResponse(BaseModel):
    session_id: int
    provider: str
    model: str | None
    summary: str
    interpreted_preferences: list[str]
    fallback_reason: str | None
    search_plan: AgentSearchPlanOut | None = None
    local: LocalRecommendationResponse | None
    internet: InternetRecommendationResponse | None


class RecommendationFeedbackRequest(BaseModel):
    session_id: int
    source: str
    action: str
    media_item_id: int | None = None
    candidate_id: int | None = None


class RecommendationFeedbackOut(BaseModel):
    id: int
    recorded: bool


class RecommendationEvaluationOut(BaseModel):
    sessions: int
    agent_sessions: int
    gemini_sessions: int
    fallback_sessions: int
    outcomes: int
    added: int
    watched: int
    dismissed: int
    selected: int
    liked: int
    disliked: int
    skipped: int
    watch_link_opens: int
    impressions: int
    positive_outcome_rate: float
    selection_rate: float
    satisfaction_rate: float
    skip_rate: float
    fallback_rate: float
