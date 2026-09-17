from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .config import PROJECT_ROOT, get_settings
from .agent_recommendations import recommend_with_agent
from .database import Base, engine, get_db
from .discovery import add_discovery_to_library, discover_internet
from .importer import normalize_title, source_domain
from .intake import commit_intake, resolve_intake
from .metadata import (
    ProviderError,
    enqueue_metadata_backfill,
    fail_job,
    metadata_readiness,
    provider_clients,
    refresh_item,
    run_queued_metadata_jobs,
    set_manual_override,
)
from .models import (
    DismissedDiscovery,
    DismissedRecommendation,
    ImportJob,
    ImportRow,
    MediaItem,
    MediaLink,
    MediaTag,
    MetadataJob,
    UserMediaState,
    WatchLaterEntry,
)
from .recommendations import recommend_local
from .recommendation_feedback import (
    recommendation_evaluation,
    record_recommendation_feedback,
)
from .schemas import (
    AddDiscoveryResponse,
    AgentRecommendationRequest,
    AgentRecommendationResponse,
    AgentStatusOut,
    DiscoveryDismissRequest,
    DismissRecommendationRequest,
    ImportRequest,
    ImportStats,
    InternetRecommendationResponse,
    IntakeCommitRequest,
    IntakeCommitResponse,
    IntakeResolveRequest,
    IntakeResolveResponse,
    LinkCreate,
    LinkOut,
    MetadataCandidate,
    MetadataBackfillRequest,
    MetadataBackfillResponse,
    MetadataJobOut,
    MetadataReadinessOut,
    MetadataResolveRequest,
    MetadataSearchRequest,
    RecommendationEvaluationOut,
    RecommendationFeedbackOut,
    RecommendationFeedbackRequest,
    LocalRecommendationRequest,
    LocalRecommendationResponse,
    ReviewResolveRequest,
    ReviewRowOut,
    TitleDetail,
    TitleListResponse,
    TitlePatch,
    WatchLaterItemOut,
    WatchLaterMoveRequest,
    WatchLaterResponse,
)
from .services import (
    commit_import,
    preview_import,
    replace_tags,
    title_detail,
    title_query,
    title_summary,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Whatch API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_item(session: Session, title_id: int) -> MediaItem:
    item = session.scalar(
        select(MediaItem)
        .where(MediaItem.id == title_id, MediaItem.archived_at.is_(None))
        .options(
            selectinload(MediaItem.links),
            selectinload(MediaItem.user_state),
            selectinload(MediaItem.tags).selectinload(MediaTag.tag),
            selectinload(MediaItem.watch_later_entry),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Title not found")
    return item


def import_stats(job: ImportJob) -> ImportStats:
    return ImportStats(
        job_id=job.id,
        total_rows=job.total_rows,
        matched_rows=job.matched_rows,
        duplicate_rows=job.duplicate_rows,
        review_rows=job.review_rows,
        canonical_candidates=job.matched_rows - job.duplicate_rows,
        status=job.status,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/intake/resolve", response_model=IntakeResolveResponse)
def resolve_title_intake(
    request: IntakeResolveRequest,
    session: Session = Depends(get_db),
) -> IntakeResolveResponse:
    try:
        return resolve_intake(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@app.post("/api/intake/commit", response_model=IntakeCommitResponse)
def commit_title_intake(
    request: IntakeCommitRequest,
    session: Session = Depends(get_db),
) -> IntakeCommitResponse:
    try:
        item, created = commit_intake(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return IntakeCommitResponse(
        item=title_detail(load_item(session, item.id)),
        created=created,
        destination=request.destination,
    )


@app.get("/api/titles", response_model=TitleListResponse)
def list_titles(
    q: str | None = None,
    media_type: str | None = None,
    status: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    imdb_min: float | None = None,
    rt_min: float | None = None,
    sort: str = "title",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> TitleListResponse:
    stmt = title_query(
        session,
        q=q,
        media_type=media_type,
        status=status,
        year_min=year_min,
        year_max=year_max,
        imdb_min=imdb_min,
        rt_min=rt_min,
        sort=sort,
    )
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return TitleListResponse(
        items=[title_summary(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def add_watch_later_entry(session: Session, item: MediaItem) -> None:
    existing = session.scalar(
        select(WatchLaterEntry).where(WatchLaterEntry.media_item_id == item.id)
    )
    if existing is None:
        session.add(WatchLaterEntry(media_item=item))
        session.commit()


@app.get("/api/watch-later", response_model=WatchLaterResponse)
def list_watch_later(session: Session = Depends(get_db)) -> WatchLaterResponse:
    entries = list(
        session.scalars(
            select(WatchLaterEntry)
            .join(WatchLaterEntry.media_item)
            .where(MediaItem.archived_at.is_(None))
            .options(
                selectinload(WatchLaterEntry.media_item).selectinload(MediaItem.links),
                selectinload(WatchLaterEntry.media_item).selectinload(MediaItem.user_state),
                selectinload(WatchLaterEntry.media_item)
                .selectinload(MediaItem.tags)
                .selectinload(MediaTag.tag),
                selectinload(WatchLaterEntry.media_item).selectinload(
                    MediaItem.watch_later_entry
                ),
            )
            .order_by(WatchLaterEntry.added_at.desc(), WatchLaterEntry.id.desc())
        ).unique()
    )
    return WatchLaterResponse(
        items=[
            WatchLaterItemOut(
                **title_summary(entry.media_item).model_dump(),
                added_at=entry.added_at,
            )
            for entry in entries
        ],
        total=len(entries),
    )


@app.post("/api/watch-later/title/{title_id}", response_model=TitleDetail)
def add_title_to_watch_later(
    title_id: int,
    session: Session = Depends(get_db),
) -> TitleDetail:
    item = load_item(session, title_id)
    add_watch_later_entry(session, item)
    session.expire(item, ["watch_later_entry"])
    return title_detail(load_item(session, title_id))


@app.delete(
    "/api/watch-later/title/{title_id}",
    status_code=204,
    response_class=Response,
)
def remove_title_from_watch_later(
    title_id: int,
    session: Session = Depends(get_db),
) -> Response:
    entry = session.scalar(
        select(WatchLaterEntry).where(WatchLaterEntry.media_item_id == title_id)
    )
    if entry is not None:
        session.delete(entry)
        session.commit()
    return Response(status_code=204)


@app.post(
    "/api/watch-later/title/{title_id}/move-to-library",
    response_model=TitleDetail,
)
def move_watch_later_to_library(
    title_id: int,
    request: WatchLaterMoveRequest,
    session: Session = Depends(get_db),
) -> TitleDetail:
    item = load_item(session, title_id)
    entry = session.scalar(
        select(WatchLaterEntry).where(WatchLaterEntry.media_item_id == title_id)
    )
    if request.watched:
        item.user_state.status = "watched"
        if item.user_state.watched_at is None:
            from datetime import datetime, timezone

            item.user_state.watched_at = datetime.now(timezone.utc)
    if entry is not None:
        session.delete(entry)
    session.commit()
    return title_detail(load_item(session, title_id))


@app.get("/api/titles/{title_id}", response_model=TitleDetail)
def get_title(title_id: int, session: Session = Depends(get_db)) -> TitleDetail:
    return title_detail(load_item(session, title_id))


@app.patch("/api/titles/{title_id}", response_model=TitleDetail)
def patch_title(
    title_id: int,
    patch: TitlePatch,
    session: Session = Depends(get_db),
) -> TitleDetail:
    item = load_item(session, title_id)
    values = patch.model_dump(exclude_unset=True)
    state_fields = {"status", "priority", "user_rating", "notes"}
    for field in state_fields:
        if field in values:
            setattr(item.user_state, field, values[field])
    if values.get("status") == "watched" and item.user_state.watched_at is None:
        from datetime import datetime, timezone

        item.user_state.watched_at = datetime.now(timezone.utc)
    elif "status" in values and values["status"] != "watched":
        item.user_state.watched_at = None
    if "tags" in values:
        replace_tags(session, item, values["tags"])
    metadata_fields = {
        "title",
        "original_title",
        "media_type",
        "start_year",
        "end_year",
        "is_ongoing",
        "runtime_minutes",
        "overview",
        "release_date",
        "poster_url",
        "original_language",
        "imdb_rating",
        "rotten_tomatoes_rating",
        "metacritic_rating",
    }
    for field in metadata_fields:
        if field in values:
            setattr(item, field, values[field])
            set_manual_override(session, item, field, values[field])
    if "genres" in values:
        item.genres_json = json.dumps(
            sorted({genre.strip() for genre in values["genres"] if genre.strip()})
        )
        set_manual_override(session, item, "genres_json", json.loads(item.genres_json))
    if "title" in values:
        item.normalized_title = normalize_title(values["title"])
    session.commit()
    return title_detail(load_item(session, title_id))


@app.post("/api/titles/{title_id}/metadata/refresh", response_model=MetadataJobOut)
def refresh_title_metadata(
    title_id: int,
    session: Session = Depends(get_db),
) -> MetadataJob:
    item = load_item(session, title_id)
    job = MetadataJob(media_item=item, job_type="refresh_item", status="queued")
    session.add(job)
    session.commit()
    job_id = job.id
    try:
        tmdb, omdb = provider_clients(get_settings())
        refresh_item(session, item, job, tmdb, omdb, force=True)
        session.commit()
    except Exception as exc:
        session.rollback()
        failed_job = session.get(MetadataJob, job_id)
        if failed_job is None:
            raise HTTPException(status_code=500, detail="Metadata job could not be recovered")
        fail_job(failed_job, exc)
        session.commit()
        if isinstance(exc, ProviderError):
            raise HTTPException(
                status_code=422,
                detail={"job_id": job_id, "code": exc.code, "message": str(exc)},
            ) from exc
        raise
    return session.get(MetadataJob, job_id)


@app.get("/api/metadata/jobs", response_model=list[MetadataJobOut])
def list_metadata_jobs(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> list[MetadataJob]:
    return list(
        session.scalars(select(MetadataJob).order_by(MetadataJob.id.desc()).limit(limit))
    )


@app.get("/api/metadata/readiness", response_model=MetadataReadinessOut)
def get_metadata_readiness(
    session: Session = Depends(get_db),
) -> dict[str, int]:
    return metadata_readiness(session)


@app.post("/api/metadata/backfill", response_model=MetadataBackfillResponse)
def backfill_metadata(
    request: MetadataBackfillRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
) -> MetadataBackfillResponse:
    job_ids = enqueue_metadata_backfill(session, request.limit)
    if job_ids:
        background_tasks.add_task(run_queued_metadata_jobs, len(job_ids))
    return MetadataBackfillResponse(
        queued_job_ids=job_ids,
        readiness=metadata_readiness(session),
    )


@app.post("/api/metadata/jobs/retry", response_model=MetadataBackfillResponse)
def retry_failed_metadata_jobs(
    request: MetadataBackfillRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
) -> MetadataBackfillResponse:
    failed_candidates = list(
        session.scalars(
            select(MetadataJob)
            .join(MediaItem, MediaItem.id == MetadataJob.media_item_id)
            .where(
                MetadataJob.status == "failed",
                MediaItem.metadata_status != "enriched",
                MediaItem.archived_at.is_(None),
            )
            .order_by(MetadataJob.id.desc())
            .limit(100)
        )
    )
    jobs = []
    seen_item_ids: set[int] = set()
    for job in failed_candidates:
        if job.media_item_id in seen_item_ids:
            continue
        seen_item_ids.add(job.media_item_id)
        jobs.append(job)
        if len(jobs) == request.limit:
            break
    for job in jobs:
        job.status = "queued"
        job.error_code = None
        job.error_message = None
        job.finished_at = None
    session.commit()
    job_ids = [job.id for job in jobs]
    if job_ids:
        background_tasks.add_task(run_queued_metadata_jobs, len(job_ids))
    return MetadataBackfillResponse(
        queued_job_ids=job_ids,
        readiness=metadata_readiness(session),
    )


@app.post("/api/metadata/search", response_model=list[MetadataCandidate])
def search_metadata(
    request: MetadataSearchRequest,
) -> list[MetadataCandidate]:
    try:
        tmdb, _ = provider_clients(get_settings())
        payload = tmdb.search(request.media_type, request.title, request.year)
    except ProviderError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    is_tv = request.media_type == "tv"
    candidates = []
    for result in (payload.get("results") or [])[:8]:
        poster_path = result.get("poster_path")
        candidates.append(
            MetadataCandidate(
                tmdb_id=result["id"],
                media_type=request.media_type,
                title=result.get("name" if is_tv else "title") or "Untitled",
                original_title=result.get(
                    "original_name" if is_tv else "original_title"
                ),
                release_date=result.get(
                    "first_air_date" if is_tv else "release_date"
                )
                or None,
                overview=result.get("overview") or None,
                poster_url=(
                    f"https://image.tmdb.org/t/p/w185{poster_path}"
                    if poster_path
                    else None
                ),
            )
        )
    return candidates


@app.post("/api/review/{row_id}/resolve-metadata", response_model=ReviewRowOut)
def resolve_review_metadata(
    row_id: int,
    request: MetadataResolveRequest,
    session: Session = Depends(get_db),
) -> ImportRow:
    row = session.get(ImportRow, row_id)
    if row is None or row.resolution_status != "pending":
        raise HTTPException(status_code=404, detail="Pending review row not found")
    if request.media_type not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type must be movie or tv")
    try:
        tmdb, _ = provider_clients(get_settings())
        details = tmdb.details(request.media_type, request.tmdb_id)
        external_ids = tmdb.external_ids(request.media_type, request.tmdb_id)
    except ProviderError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    imdb_id = external_ids.get("imdb_id")
    if not imdb_id:
        raise HTTPException(
            status_code=422,
            detail="Selected TMDB title has no IMDb identity; resolve it manually",
        )

    item = session.scalar(
        select(MediaItem)
        .where(MediaItem.imdb_id == imdb_id)
        .options(selectinload(MediaItem.links), selectinload(MediaItem.user_state))
    )
    created = item is None
    is_tv = request.media_type == "tv"
    release_date = details.get("first_air_date" if is_tv else "release_date") or None
    if created:
        provider_title = details.get("name" if is_tv else "title") or row.raw_title
        runtime = (
            next(iter(details.get("episode_run_time") or []), None)
            if is_tv
            else details.get("runtime")
        )
        item = MediaItem(
            title=provider_title,
            normalized_title=normalize_title(provider_title),
            original_title=details.get(
                "original_name" if is_tv else "original_title"
            ),
            media_type=request.media_type,
            start_year=int(release_date[:4]) if release_date else None,
            release_date=release_date,
            runtime_minutes=runtime,
            overview=details.get("overview") or None,
            genres_json=json.dumps(
                [genre["name"] for genre in details.get("genres", []) if genre.get("name")]
            ),
            original_language=details.get("original_language"),
            production_countries_json=json.dumps(
                [
                    country["iso_3166_1"].upper()
                    for country in details.get("production_countries", [])
                    if country.get("iso_3166_1")
                ]
            ),
            poster_url=(
                f"https://image.tmdb.org/t/p/w500{details['poster_path']}"
                if details.get("poster_path")
                else None
            ),
            imdb_id=imdb_id,
            tmdb_id=request.tmdb_id,
            tmdb_media_type=request.media_type,
            tmdb_vote_average=details.get("vote_average"),
            tmdb_vote_count=details.get("vote_count"),
            metadata_status="matched",
        )
        item.user_state = UserMediaState(status="want_to_watch", priority="normal")
        session.add(item)
        session.flush()
    if row.raw_url and not any(link.url == row.raw_url for link in item.links):
        item.links.append(
            MediaLink(
                url=row.raw_url,
                domain=source_domain(row.raw_url),
                link_type="source",
                original_label="bookmark",
            )
        )
    row.resolved_media_item_id = item.id
    row.resolution_status = "created" if created else "merged"
    session.commit()
    session.refresh(row)
    return row


@app.post("/api/titles/{title_id}/links", response_model=LinkOut)
def add_title_link(
    title_id: int,
    request: LinkCreate,
    session: Session = Depends(get_db),
) -> MediaLink:
    item = load_item(session, title_id)
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Link must use HTTP or HTTPS")
    existing = next((link for link in item.links if link.url == request.url), None)
    if existing:
        existing.archived = False
        session.commit()
        session.refresh(existing)
        return existing
    link = MediaLink(
        media_item=item,
        url=request.url,
        domain=source_domain(request.url),
        link_type=request.link_type,
        original_label=request.original_label,
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


@app.delete(
    "/api/titles/{title_id}/links/{link_id}",
    status_code=204,
    response_class=Response,
)
def archive_title_link(
    title_id: int,
    link_id: int,
    session: Session = Depends(get_db),
) -> Response:
    link = session.scalar(
        select(MediaLink).where(
            MediaLink.id == link_id, MediaLink.media_item_id == title_id
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    link.archived = True
    session.commit()
    return Response(status_code=204)


@app.post("/api/recommend/local", response_model=LocalRecommendationResponse)
def local_recommendations(
    request: LocalRecommendationRequest,
    session: Session = Depends(get_db),
) -> LocalRecommendationResponse:
    if request.media_type not in {"either", "movie", "tv"}:
        raise HTTPException(status_code=400, detail="Invalid media_type")
    if request.adventure not in {"safe", "adjacent", "adventurous"}:
        raise HTTPException(status_code=400, detail="Invalid adventure level")
    return recommend_local(session, request)


@app.get("/api/recommend/agent/status", response_model=AgentStatusOut)
def recommendation_agent_status() -> AgentStatusOut:
    settings = get_settings()
    configured = bool(settings.gemini_api_key)
    return AgentStatusOut(
        available=settings.gemini_enabled and configured,
        enabled=settings.gemini_enabled,
        configured=configured,
        model=settings.gemini_model,
        privacy_summary=(
            "Gemini receives only the request, compact validated candidates, and "
            "public metadata. Notes and the full catalog remain local."
        ),
    )


@app.post("/api/recommend/feedback", response_model=RecommendationFeedbackOut)
def recommendation_feedback(
    request: RecommendationFeedbackRequest,
    session: Session = Depends(get_db),
) -> RecommendationFeedbackOut:
    try:
        outcome, recorded = record_recommendation_feedback(session, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return RecommendationFeedbackOut(id=outcome.id, recorded=recorded)


@app.get("/api/recommend/evaluation", response_model=RecommendationEvaluationOut)
def recommendation_metrics(
    session: Session = Depends(get_db),
) -> RecommendationEvaluationOut:
    return recommendation_evaluation(session)


@app.post("/api/recommend/agent", response_model=AgentRecommendationResponse)
async def agent_recommendations(
    request: AgentRecommendationRequest,
    session: Session = Depends(get_db),
) -> AgentRecommendationResponse:
    if request.media_type not in {"either", "movie", "tv"}:
        raise HTTPException(status_code=400, detail="Invalid media_type")
    if request.adventure not in {"safe", "adjacent", "adventurous"}:
        raise HTTPException(status_code=400, detail="Invalid adventure level")
    if request.scope not in {"local", "internet", "hybrid"}:
        raise HTTPException(status_code=400, detail="Invalid recommendation scope")
    try:
        return await recommend_with_agent(session, request, get_settings())
    except ProviderError as exc:
        session.rollback()
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": str(exc)},
        ) from None


@app.post("/api/recommend/dismiss/{title_id}", status_code=204, response_class=Response)
def dismiss_recommendation(
    title_id: int,
    request: DismissRecommendationRequest,
    session: Session = Depends(get_db),
) -> Response:
    item = load_item(session, title_id)
    dismissal = session.scalar(
        select(DismissedRecommendation).where(
            DismissedRecommendation.media_item_id == item.id
        )
    )
    if dismissal is None:
        session.add(
            DismissedRecommendation(media_item=item, reason=request.reason)
        )
    else:
        dismissal.reason = request.reason
    session.commit()
    return Response(status_code=204)


@app.delete(
    "/api/recommend/dismiss/{title_id}",
    status_code=204,
    response_class=Response,
)
def restore_recommendation(
    title_id: int,
    session: Session = Depends(get_db),
) -> Response:
    dismissal = session.scalar(
        select(DismissedRecommendation).where(
            DismissedRecommendation.media_item_id == title_id
        )
    )
    if dismissal:
        session.delete(dismissal)
        session.commit()
    return Response(status_code=204)


@app.post("/api/recommend/internet", response_model=InternetRecommendationResponse)
def internet_recommendations(
    request: LocalRecommendationRequest,
    session: Session = Depends(get_db),
) -> InternetRecommendationResponse:
    if request.media_type not in {"either", "movie", "tv"}:
        raise HTTPException(status_code=400, detail="Invalid media_type")
    if request.adventure not in {"safe", "adjacent", "adventurous"}:
        raise HTTPException(status_code=400, detail="Invalid adventure level")
    try:
        tmdb, omdb = provider_clients(get_settings())
        return discover_internet(session, request, tmdb, omdb)
    except ProviderError as exc:
        session.rollback()
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": str(exc)},
        ) from None


@app.post(
    "/api/recommend/internet/dismiss/{media_type}/{tmdb_id}",
    status_code=204,
    response_class=Response,
)
def dismiss_internet_recommendation(
    media_type: str,
    tmdb_id: int,
    request: DiscoveryDismissRequest,
    session: Session = Depends(get_db),
) -> Response:
    dismissal = session.scalar(
        select(DismissedDiscovery).where(
            DismissedDiscovery.media_type == media_type,
            DismissedDiscovery.tmdb_id == tmdb_id,
        )
    )
    if dismissal is None:
        session.add(
            DismissedDiscovery(
                media_type=media_type,
                tmdb_id=tmdb_id,
                reason=request.reason,
            )
        )
    else:
        dismissal.reason = request.reason
    session.commit()
    return Response(status_code=204)


@app.post(
    "/api/recommend/internet/add/{candidate_id}",
    response_model=AddDiscoveryResponse,
)
def add_internet_recommendation(
    candidate_id: int,
    session: Session = Depends(get_db),
) -> AddDiscoveryResponse:
    try:
        item, created = add_discovery_to_library(session, candidate_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return AddDiscoveryResponse(media_item_id=item.id, created=created)


@app.post(
    "/api/watch-later/discovery/{candidate_id}",
    response_model=TitleDetail,
)
def add_discovery_to_watch_later(
    candidate_id: int,
    session: Session = Depends(get_db),
) -> TitleDetail:
    try:
        item, _created = add_discovery_to_library(session, candidate_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    add_watch_later_entry(session, item)
    session.expire(item, ["watch_later_entry"])
    return title_detail(load_item(session, item.id))


@app.post("/api/import/markdown", response_model=ImportStats)
def create_import_preview(
    request: ImportRequest,
    session: Session = Depends(get_db),
) -> ImportStats:
    settings = get_settings()
    source_path = Path(request.source_path).resolve() if request.source_path else settings.catalog_source
    if not source_path.is_relative_to(PROJECT_ROOT) or source_path.suffix.casefold() != ".md":
        raise HTTPException(status_code=400, detail="Import path must be a Markdown file in the project")
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Import source not found")
    return import_stats(preview_import(session, source_path))


@app.get("/api/import/preview/{job_id}", response_model=ImportStats)
def get_import_preview(job_id: int, session: Session = Depends(get_db)) -> ImportStats:
    job = session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return import_stats(job)


@app.post("/api/import/commit/{job_id}", response_model=ImportStats)
def commit_import_job(job_id: int, session: Session = Depends(get_db)) -> ImportStats:
    job = session.scalar(
        select(ImportJob).where(ImportJob.id == job_id).options(selectinload(ImportJob.rows))
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return import_stats(commit_import(session, job))


@app.get("/api/import/latest", response_model=ImportStats | None)
def latest_import(session: Session = Depends(get_db)):
    job = session.scalar(select(ImportJob).order_by(ImportJob.id.desc()).limit(1))
    return import_stats(job) if job else None


@app.get("/api/review", response_model=list[ReviewRowOut])
def review_queue(session: Session = Depends(get_db)) -> list[ImportRow]:
    return list(
        session.scalars(
            select(ImportRow)
            .where(ImportRow.resolution_status == "pending")
            .order_by(ImportRow.normalized_title, ImportRow.id)
        )
    )


@app.post("/api/review/{row_id}/resolve", response_model=ReviewRowOut)
def resolve_review(
    row_id: int,
    request: ReviewResolveRequest,
    session: Session = Depends(get_db),
) -> ImportRow:
    row = session.get(ImportRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Review row not found")
    if request.action == "ignore":
        row.resolution_status = "ignored"
    elif request.action == "merge":
        if not request.media_item_id:
            raise HTTPException(status_code=400, detail="media_item_id is required")
        load_item(session, request.media_item_id)
        row.resolved_media_item_id = request.media_item_id
        row.resolution_status = "merged"
    elif request.action == "create":
        title = request.title or row.raw_title
        item = MediaItem(
            title=title,
            normalized_title=normalize_title(title),
            original_title=row.raw_title,
            media_type=request.media_type or row.raw_section,
            start_year=request.start_year,
            metadata_status="manual",
        )
        item.user_state = UserMediaState(status="want_to_watch", priority="normal")
        if row.raw_url:
            item.links.append(
                MediaLink(
                    url=row.raw_url,
                    domain=source_domain(row.raw_url),
                    link_type="source",
                    original_label="bookmark",
                )
            )
        session.add(item)
        session.flush()
        row.resolved_media_item_id = item.id
        row.resolution_status = "created"
    else:
        raise HTTPException(status_code=400, detail="Unknown review action")
    session.commit()
    session.refresh(row)
    return row


@app.get("/api/export/json")
def export_json(session: Session = Depends(get_db)) -> JSONResponse:
    items = session.scalars(
        select(MediaItem)
        .where(MediaItem.archived_at.is_(None))
        .options(
            selectinload(MediaItem.links),
            selectinload(MediaItem.user_state),
            selectinload(MediaItem.tags).selectinload(MediaTag.tag),
        )
        .order_by(MediaItem.title)
    ).all()
    payload = {
        "version": 1,
        "titles": [title_detail(item).model_dump(mode="json") for item in items],
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="whatch-export.json"'},
    )


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=FRONTEND_DIST, html=True),
        name="frontend",
    )
