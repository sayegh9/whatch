from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import SessionLocal
from .models import ManualOverride, MediaItem, MetadataJob, ProviderSnapshot


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TmdbProvider(Protocol):
    def find_by_imdb(self, imdb_id: str) -> dict[str, Any]: ...

    def details(self, media_type: str, tmdb_id: int) -> dict[str, Any]: ...

    def external_ids(self, media_type: str, tmdb_id: int) -> dict[str, Any]: ...

    def search(self, media_type: str, query: str, year: int | None) -> dict[str, Any]: ...

    def recommendations(self, media_type: str, tmdb_id: int) -> dict[str, Any]: ...

    def discover(self, media_type: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def genre_list(self, media_type: str) -> dict[str, Any]: ...


class OmdbProvider(Protocol):
    def by_imdb(self, imdb_id: str) -> dict[str, Any]: ...


class TmdbClient:
    base_url = "https://api.themoviedb.org/3"

    def __init__(
        self,
        token: str,
        language: str = "en-US",
        transport: httpx.BaseTransport | None = None,
    ):
        self.language = language
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
            timeout=12,
            transport=transport,
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("tmdb_request_failed", f"TMDB request failed: {exc}") from exc

    def find_by_imdb(self, imdb_id: str) -> dict[str, Any]:
        return self._get(
            f"/find/{imdb_id}",
            {"external_source": "imdb_id", "language": self.language},
        )

    def details(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        endpoint = "tv" if media_type == "tv" else "movie"
        return self._get(f"/{endpoint}/{tmdb_id}", {"language": self.language})

    def external_ids(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        endpoint = "tv" if media_type == "tv" else "movie"
        return self._get(f"/{endpoint}/{tmdb_id}/external_ids")

    def search(self, media_type: str, query: str, year: int | None) -> dict[str, Any]:
        endpoint = "tv" if media_type == "tv" else "movie"
        params: dict[str, Any] = {"query": query, "language": self.language}
        if year:
            params["first_air_date_year" if endpoint == "tv" else "year"] = year
        return self._get(f"/search/{endpoint}", params)

    def recommendations(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        endpoint = "tv" if media_type == "tv" else "movie"
        return self._get(
            f"/{endpoint}/{tmdb_id}/recommendations",
            {"language": self.language, "page": 1},
        )

    def discover(self, media_type: str, params: dict[str, Any]) -> dict[str, Any]:
        endpoint = "tv" if media_type == "tv" else "movie"
        return self._get(
            f"/discover/{endpoint}",
            {"language": self.language, "page": 1, "include_adult": False, **params},
        )

    def genre_list(self, media_type: str) -> dict[str, Any]:
        endpoint = "tv" if media_type == "tv" else "movie"
        return self._get(f"/genre/{endpoint}/list", {"language": self.language})


class OmdbClient:
    base_url = "https://www.omdbapi.com"

    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.client = httpx.Client(base_url=self.base_url, timeout=12, transport=transport)

    def by_imdb(self, imdb_id: str) -> dict[str, Any]:
        try:
            response = self.client.get("/", params={"apikey": self.api_key, "i": imdb_id})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                "omdb_request_failed",
                f"OMDb request failed with HTTP {exc.response.status_code}",
            ) from None
        except (httpx.RequestError, ValueError) as exc:
            raise ProviderError("omdb_request_failed", "OMDb request failed") from None
        if payload.get("Response") == "False":
            raise ProviderError("omdb_not_found", payload.get("Error", "OMDb title not found"))
        return payload


def provider_clients(settings: Settings) -> tuple[TmdbClient, OmdbClient]:
    if not settings.tmdb_api_token:
        raise ProviderError("tmdb_not_configured", "TMDB_API_TOKEN is not configured")
    if not settings.omdb_api_key:
        raise ProviderError("omdb_not_configured", "OMDB_API_KEY is not configured")
    return (
        TmdbClient(settings.tmdb_api_token, settings.metadata_language),
        OmdbClient(settings.omdb_api_key),
    )


def snapshot(
    session: Session,
    item: MediaItem,
    provider: str,
    cache_key: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        ProviderSnapshot(
            media_item=item,
            provider=provider,
            cache_key=cache_key,
            response_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
    )


def cached_snapshot(
    session: Session,
    item: MediaItem,
    provider: str,
    cache_key: str,
) -> dict[str, Any] | None:
    record = session.scalar(
        select(ProviderSnapshot)
        .where(
            ProviderSnapshot.media_item_id == item.id,
            ProviderSnapshot.provider == provider,
            ProviderSnapshot.cache_key == cache_key,
        )
        .order_by(ProviderSnapshot.fetched_at.desc(), ProviderSnapshot.id.desc())
        .limit(1)
    )
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
    try:
        return json.loads(record.response_json)
    except json.JSONDecodeError:
        return None


def cached_provider_call(
    session: Session,
    item: MediaItem,
    provider: str,
    cache_key: str,
    loader,
    *,
    force: bool,
) -> dict[str, Any]:
    if not force:
        cached = cached_snapshot(session, item, provider, cache_key)
        if cached is not None:
            return cached
    payload = loader()
    snapshot(session, item, provider, cache_key, payload)
    return payload


def manual_fields(session: Session, item_id: int) -> set[str]:
    return set(
        session.scalars(
            select(ManualOverride.field_name).where(ManualOverride.media_item_id == item_id)
        )
    )


def set_manual_override(
    session: Session, item: MediaItem, field_name: str, value: Any
) -> None:
    override = session.scalar(
        select(ManualOverride).where(
            ManualOverride.media_item_id == item.id,
            ManualOverride.field_name == field_name,
        )
    )
    encoded = json.dumps(value, separators=(",", ":"))
    if override is None:
        session.add(
            ManualOverride(media_item=item, field_name=field_name, value_json=encoded)
        )
    else:
        override.value_json = encoded


def _number(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def _year(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _select_tmdb_match(item: MediaItem, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    preferred = "tv_results" if item.media_type == "tv" else "movie_results"
    alternate = "movie_results" if preferred == "tv_results" else "tv_results"
    preferred_results = payload.get(preferred) or []
    if preferred_results:
        return item.media_type, preferred_results[0]
    alternate_results = payload.get(alternate) or []
    if alternate_results:
        return ("movie" if alternate == "movie_results" else "tv"), alternate_results[0]
    raise ProviderError("tmdb_identity_not_found", f"No TMDB match for {item.imdb_id}")


def refresh_item(
    session: Session,
    item: MediaItem,
    job: MetadataJob,
    tmdb: TmdbProvider,
    omdb: OmdbProvider,
    *,
    force: bool = False,
) -> MediaItem:
    if not item.imdb_id:
        raise ProviderError("missing_imdb_id", "An IMDb ID is required for safe refresh")

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.attempts += 1
    session.flush()

    find_key = f"find:imdb:{item.imdb_id}"
    find_payload = cached_provider_call(
        session,
        item,
        "tmdb",
        find_key,
        lambda: tmdb.find_by_imdb(item.imdb_id),
        force=force,
    )
    tmdb_type, match = _select_tmdb_match(item, find_payload)
    details_key = f"{tmdb_type}:{match['id']}"
    details = cached_provider_call(
        session,
        item,
        "tmdb",
        details_key,
        lambda: tmdb.details(tmdb_type, int(match["id"])),
        force=force,
    )
    omdb_key = f"imdb:{item.imdb_id}"
    omdb_payload = cached_provider_call(
        session,
        item,
        "omdb",
        omdb_key,
        lambda: omdb.by_imdb(item.imdb_id),
        force=force,
    )

    is_tv = tmdb_type == "tv"
    release_date = details.get("first_air_date" if is_tv else "release_date") or None
    runtime = (
        next(iter(details.get("episode_run_time") or []), None)
        if is_tv
        else details.get("runtime")
    )
    end_date = details.get("last_air_date") if is_tv else None
    resolved: dict[str, Any] = {
        "title": details.get("name" if is_tv else "title") or item.title,
        "original_title": details.get("original_name" if is_tv else "original_title"),
        "media_type": tmdb_type,
        "start_year": _year(release_date),
        "end_year": _year(end_date),
        "is_ongoing": bool(details.get("in_production")) if is_tv else False,
        "release_date": release_date,
        "runtime_minutes": runtime,
        "overview": details.get("overview") or None,
        "genres_json": json.dumps(
            [genre["name"] for genre in details.get("genres", []) if genre.get("name")]
        ),
        "original_language": details.get("original_language"),
        "production_countries_json": json.dumps(
            [
                country["iso_3166_1"].upper()
                for country in details.get("production_countries", [])
                if country.get("iso_3166_1")
            ]
        ),
        "poster_url": (
            f"https://image.tmdb.org/t/p/w500{details['poster_path']}"
            if details.get("poster_path")
            else None
        ),
        "tmdb_id": int(details["id"]),
        "tmdb_media_type": tmdb_type,
        "tmdb_vote_average": _number(details.get("vote_average")),
        "tmdb_vote_count": details.get("vote_count"),
        "imdb_rating": _number(omdb_payload.get("imdbRating")),
        "metacritic_rating": _number(omdb_payload.get("Metascore")),
    }
    for rating in omdb_payload.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            resolved["rotten_tomatoes_rating"] = _number(rating.get("Value"))

    protected = manual_fields(session, item.id)
    for field, value in resolved.items():
        if field not in protected and value is not None:
            setattr(item, field, value)
    if "title" not in protected:
        from .importer import normalize_title

        item.normalized_title = normalize_title(item.title)
    item.metadata_status = "enriched"
    item.metadata_refreshed_at = datetime.now(timezone.utc)
    job.status = "succeeded"
    job.finished_at = datetime.now(timezone.utc)
    return item


def fail_job(job: MetadataJob, error: Exception) -> None:
    job.status = "failed"
    job.attempts = max(job.attempts, 1)
    job.started_at = job.started_at or datetime.now(timezone.utc)
    job.finished_at = datetime.now(timezone.utc)
    job.error_code = error.code if isinstance(error, ProviderError) else "unexpected_error"
    job.error_message = str(error)[:2000]


def metadata_readiness(session: Session) -> dict[str, int]:
    base = MediaItem.archived_at.is_(None)
    total = session.scalar(select(func.count(MediaItem.id)).where(base)) or 0
    eligible = (
        session.scalar(
            select(func.count(MediaItem.id)).where(base, MediaItem.imdb_id.is_not(None))
        )
        or 0
    )
    return {
        "total": total,
        "eligible": eligible,
        "enriched": session.scalar(
            select(func.count(MediaItem.id)).where(base, MediaItem.metadata_status == "enriched")
        )
        or 0,
        "runtime": session.scalar(
            select(func.count(MediaItem.id)).where(base, MediaItem.runtime_minutes.is_not(None))
        )
        or 0,
        "genres": session.scalar(
            select(func.count(MediaItem.id)).where(base, MediaItem.genres_json != "[]")
        )
        or 0,
        "overview": session.scalar(
            select(func.count(MediaItem.id)).where(base, MediaItem.overview.is_not(None))
        )
        or 0,
        "queued": session.scalar(
            select(func.count(MetadataJob.id)).where(MetadataJob.status == "queued")
        )
        or 0,
        "running": session.scalar(
            select(func.count(MetadataJob.id)).where(MetadataJob.status == "running")
        )
        or 0,
        "failed": session.scalar(
            select(func.count(func.distinct(MetadataJob.media_item_id)))
            .join(MediaItem, MediaItem.id == MetadataJob.media_item_id)
            .where(
                MetadataJob.status == "failed",
                MediaItem.metadata_status != "enriched",
                MediaItem.archived_at.is_(None),
            )
        )
        or 0,
    }


def enqueue_metadata_backfill(session: Session, limit: int) -> list[int]:
    active_items = select(MetadataJob.media_item_id).where(
        MetadataJob.status.in_(("queued", "running")),
        MetadataJob.media_item_id.is_not(None),
    )
    items = list(
        session.scalars(
            select(MediaItem)
            .where(
                MediaItem.archived_at.is_(None),
                MediaItem.imdb_id.is_not(None),
                MediaItem.metadata_status != "enriched",
                MediaItem.id.not_in(active_items),
            )
            .order_by(
                (MediaItem.overview.is_(None)).desc(),
                MediaItem.updated_at.asc(),
                MediaItem.id.asc(),
            )
            .limit(limit)
        )
    )
    jobs = [
        MetadataJob(media_item=item, job_type="backfill_item", status="queued")
        for item in items
    ]
    session.add_all(jobs)
    session.commit()
    return [job.id for job in jobs]


def run_queued_metadata_jobs(limit: int) -> None:
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=15)
    with SessionLocal() as session:
        session.execute(
            update(MetadataJob)
            .where(
                MetadataJob.status == "running",
                MetadataJob.started_at < stale_before,
            )
            .values(status="queued", started_at=None)
        )
        session.commit()
    try:
        tmdb, omdb = provider_clients(get_settings())
    except Exception as exc:
        with SessionLocal() as session:
            queued = list(
                session.scalars(
                    select(MetadataJob)
                    .where(MetadataJob.status == "queued")
                    .order_by(MetadataJob.id)
                    .limit(limit)
                )
            )
            for job in queued:
                fail_job(job, exc)
            session.commit()
        return
    processed = 0
    while processed < limit:
        with SessionLocal() as session:
            job_id = session.scalar(
                select(MetadataJob.id)
                .where(MetadataJob.status == "queued")
                .order_by(MetadataJob.id)
                .limit(1)
            )
            if job_id is None:
                return
            claimed = session.execute(
                update(MetadataJob)
                .where(MetadataJob.id == job_id, MetadataJob.status == "queued")
                .values(
                    status="running",
                    started_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            if claimed.rowcount != 1:
                continue
            try:
                job = session.get(MetadataJob, job_id)
                item = session.get(MediaItem, job.media_item_id)
                if item is None:
                    raise ProviderError("title_not_found", "Title no longer exists")
                refresh_item(session, item, job, tmdb, omdb)
                session.commit()
            except Exception as exc:
                session.rollback()
                failed = session.get(MetadataJob, job_id)
                if failed is not None:
                    fail_job(failed, exc)
                    session.commit()
            processed += 1
