from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.parse import unquote, urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .importer import normalize_title, source_domain
from .metadata import ProviderError, manual_fields, provider_clients
from .models import MediaItem, MediaLink, UserMediaState, WatchLaterEntry
from .schemas import (
    IntakeCandidate,
    IntakeCommitRequest,
    IntakeResolveRequest,
    IntakeResolveResponse,
)


IMDB_ID_RE = re.compile(r"^tt\d{5,12}$", re.IGNORECASE)
TMDB_PATH_RE = re.compile(r"^/(movie|tv)/(\d+)(?:/|$)", re.IGNORECASE)


def _number(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return None


def _year(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _trusted_host(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def parse_intake_input(value: str) -> tuple[str, str, dict[str, str | int]]:
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "title", cleaned, {}

    host = parsed.hostname.casefold().rstrip(".")
    if _trusted_host(host, "imdb.com"):
        match = re.search(r"/(?:title|name)/(tt\d{5,12})(?:/|$)", parsed.path, re.I)
        if not match:
            raise ValueError("Use a direct IMDb title link, such as imdb.com/title/tt1234567/")
        imdb_id = match.group(1).lower()
        if not IMDB_ID_RE.match(imdb_id):
            raise ValueError("The IMDb title identifier is invalid")
        return "imdb_url", imdb_id, {"imdb_id": imdb_id}

    if _trusted_host(host, "themoviedb.org"):
        match = TMDB_PATH_RE.match(parsed.path)
        if not match:
            raise ValueError("Use a direct TMDB movie or TV title link")
        return (
            "tmdb_url",
            f"{match.group(1).lower()}:{match.group(2)}",
            {"media_type": match.group(1).lower(), "tmdb_id": int(match.group(2))},
        )

    if _trusted_host(host, "rottentomatoes.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[0].casefold() not in {"m", "tv"}:
            raise ValueError("Use a direct Rotten Tomatoes movie or TV title link")
        media_type = "movie" if parts[0].casefold() == "m" else "tv"
        title = unquote(parts[1]).replace("_", " ").replace("-", " ").strip()
        if not title:
            raise ValueError("The Rotten Tomatoes link does not contain a title")
        return "rt_url", title, {"media_type": media_type, "title": title}

    raise ValueError("Supported links are direct IMDb, TMDB, or Rotten Tomatoes title pages")


def _poster_url(payload: dict, size: str = "w342") -> str | None:
    path = payload.get("poster_path")
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else None


def _candidate_from_payload(
    session: Session,
    payload: dict,
    media_type: str,
    *,
    imdb_id: str | None = None,
) -> IntakeCandidate:
    is_tv = media_type == "tv"
    tmdb_id = int(payload["id"])
    existing = session.scalar(
        select(MediaItem.id).where(
            or_(
                (MediaItem.tmdb_id == tmdb_id)
                & (MediaItem.tmdb_media_type == media_type),
                MediaItem.imdb_id == imdb_id if imdb_id else False,
            )
        )
    )
    return IntakeCandidate(
        tmdb_id=tmdb_id,
        media_type=media_type,
        title=payload.get("name" if is_tv else "title") or "Untitled",
        original_title=payload.get("original_name" if is_tv else "original_title"),
        release_date=payload.get("first_air_date" if is_tv else "release_date") or None,
        overview=payload.get("overview") or None,
        poster_url=_poster_url(payload),
        tmdb_vote_average=_number(payload.get("vote_average")),
        existing_media_item_id=existing,
    )


def resolve_intake(session: Session, request: IntakeResolveRequest) -> IntakeResolveResponse:
    input_kind, normalized, identity = parse_intake_input(request.input)
    tmdb, _omdb = provider_clients(get_settings())
    candidates: list[IntakeCandidate] = []
    exact = input_kind in {"imdb_url", "tmdb_url"}

    if input_kind == "imdb_url":
        imdb_id = str(identity["imdb_id"])
        payload = tmdb.find_by_imdb(imdb_id)
        for key, media_type in (("movie_results", "movie"), ("tv_results", "tv")):
            if payload.get(key):
                match = payload[key][0]
                details = tmdb.details(media_type, int(match["id"]))
                candidates.append(
                    _candidate_from_payload(
                        session, details, media_type, imdb_id=imdb_id
                    )
                )
                break
    elif input_kind == "tmdb_url":
        media_type = str(identity["media_type"])
        tmdb_id = int(identity["tmdb_id"])
        details = tmdb.details(media_type, tmdb_id)
        candidates.append(_candidate_from_payload(session, details, media_type))
    else:
        requested_type = (
            str(identity.get("media_type"))
            if input_kind == "rt_url"
            else request.media_type
        )
        query = str(identity.get("title") or normalized)
        media_types = [requested_type] if requested_type in {"movie", "tv"} else ["movie", "tv"]
        ranked: list[tuple[float, IntakeCandidate]] = []
        for media_type in media_types:
            payload = tmdb.search(media_type, query, None)
            for result in (payload.get("results") or [])[:8]:
                candidate = _candidate_from_payload(session, result, media_type)
                rank = float(result.get("popularity") or 0) + float(
                    result.get("vote_count") or 0
                ) / 1000
                ranked.append((rank, candidate))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
        seen: set[tuple[str, int]] = set()
        for _rank, candidate in ranked:
            key = (candidate.media_type, candidate.tmdb_id)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
            if len(candidates) == 8:
                break

    if not candidates:
        raise ProviderError("intake_not_found", "No matching movie or TV title was found")
    return IntakeResolveResponse(
        input_kind=input_kind,
        exact=exact and len(candidates) == 1,
        normalized_input=normalized,
        source_url=request.input.strip() if input_kind != "title" else None,
        candidates=candidates,
    )


def commit_intake(
    session: Session,
    request: IntakeCommitRequest,
) -> tuple[MediaItem, bool]:
    tmdb, omdb = provider_clients(get_settings())
    details = tmdb.details(request.media_type, request.tmdb_id)
    external_ids = tmdb.external_ids(request.media_type, request.tmdb_id)
    imdb_id = external_ids.get("imdb_id") or None
    is_tv = request.media_type == "tv"
    release_date = details.get("first_air_date" if is_tv else "release_date") or None
    provider_title = details.get("name" if is_tv else "title") or "Untitled"
    start_year = _year(release_date)

    id_conditions = [
        (MediaItem.tmdb_id == request.tmdb_id)
        & (MediaItem.tmdb_media_type == request.media_type)
    ]
    if imdb_id:
        id_conditions.append(MediaItem.imdb_id == imdb_id)
    item = session.scalar(
        select(MediaItem)
        .where(or_(*id_conditions))
        .options(
            selectinload(MediaItem.links),
            selectinload(MediaItem.user_state),
            selectinload(MediaItem.watch_later_entry),
        )
    )
    if item is None:
        item = session.scalar(
            select(MediaItem)
            .where(
                MediaItem.normalized_title == normalize_title(provider_title),
                MediaItem.media_type == request.media_type,
                MediaItem.start_year == start_year,
                MediaItem.imdb_id.is_(None),
                MediaItem.tmdb_id.is_(None),
            )
            .options(
                selectinload(MediaItem.links),
                selectinload(MediaItem.user_state),
                selectinload(MediaItem.watch_later_entry),
            )
        )
    created = item is None
    omdb_payload: dict = {}
    if imdb_id:
        try:
            omdb_payload = omdb.by_imdb(imdb_id)
        except ProviderError:
            omdb_payload = {}

    runtime = (
        next(iter(details.get("episode_run_time") or []), None)
        if is_tv
        else details.get("runtime")
    )
    end_date = details.get("last_air_date") if is_tv else None
    values = {
        "title": provider_title,
        "normalized_title": normalize_title(provider_title),
        "original_title": details.get("original_name" if is_tv else "original_title"),
        "media_type": request.media_type,
        "start_year": start_year,
        "end_year": _year(end_date),
        "is_ongoing": bool(details.get("in_production")) if is_tv else False,
        "release_date": release_date,
        "runtime_minutes": runtime,
        "genres_json": json.dumps(
            [genre["name"] for genre in details.get("genres", []) if genre.get("name")]
        ),
        "overview": details.get("overview") or None,
        "poster_url": _poster_url(details, "w500"),
        "original_language": details.get("original_language"),
        "production_countries_json": json.dumps(
            [
                country["iso_3166_1"].upper()
                for country in details.get("production_countries", [])
                if country.get("iso_3166_1")
            ]
        ),
        "imdb_id": imdb_id,
        "imdb_rating": _number(omdb_payload.get("imdbRating")),
        "metacritic_rating": _number(omdb_payload.get("Metascore")),
        "tmdb_id": request.tmdb_id,
        "tmdb_media_type": request.media_type,
        "tmdb_vote_average": _number(details.get("vote_average")),
        "tmdb_vote_count": details.get("vote_count"),
        "metadata_status": "enriched" if omdb_payload else "matched",
        "metadata_refreshed_at": datetime.now(timezone.utc),
    }
    for rating in omdb_payload.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            values["rotten_tomatoes_rating"] = _number(rating.get("Value"))

    if created:
        item = MediaItem(**values)
        item.user_state = UserMediaState(status="want_to_watch", priority="normal")
        session.add(item)
        session.flush()
    else:
        protected = manual_fields(session, item.id)
        for field, value in values.items():
            if value is not None and field not in protected:
                setattr(item, field, value)

    links = {
        f"https://www.themoviedb.org/{request.media_type}/{request.tmdb_id}": (
            "metadata",
            "TMDB",
        )
    }
    if imdb_id:
        links[f"https://www.imdb.com/title/{imdb_id}/"] = ("metadata", "IMDb")
    if request.source_url:
        input_kind, _normalized, _identity = parse_intake_input(request.source_url)
        if input_kind == "title":
            raise ValueError("The source URL is invalid")
        links[request.source_url] = ("source", "added manually")
    existing_urls = {link.url for link in item.links}
    for url, (link_type, label) in links.items():
        if url not in existing_urls:
            item.links.append(
                MediaLink(
                    url=url,
                    domain=source_domain(url),
                    link_type=link_type,
                    original_label=label,
                )
            )

    if request.destination == "watch_later" and item.watch_later_entry is None:
        session.add(WatchLaterEntry(media_item=item))
    session.commit()
    session.refresh(item)
    return item, created
