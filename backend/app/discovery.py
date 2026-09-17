from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .importer import normalize_title
from .metadata import OmdbProvider, ProviderError, TmdbProvider
from .models import (
    DiscoveryCandidate,
    DismissedDiscovery,
    MediaItem,
    MediaLink,
    MediaTag,
    RecommendationSession,
    UserMediaState,
)
from .recommendations import (
    SelectionFacets,
    derive_taste_profile,
    feedback_preference_scores,
    item_production_countries,
    request_context_text,
    selection_similarity,
    semantic_cosines,
    semantic_tokens,
)
from .schemas import (
    DiscoveryResultOut,
    InternetRecommendationResponse,
    LocalRecommendationRequest,
)


INTERNET_WEIGHTS = {
    "seed_similarity": 0.18,
    "semantic_similarity": 0.17,
    "taste_similarity": 0.10,
    "feedback_match": 0.10,
    "genre_keyword_match": 0.08,
    "rating_quality": 0.14,
    "criteria_match": 0.12,
    "novelty": 0.06,
    "metadata_quality": 0.05,
}


def _number(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def _year(value: str | None) -> int | None:
    try:
        return int(value[:4]) if value else None
    except ValueError:
        return None


def _not_expired(candidate: DiscoveryCandidate) -> bool:
    if candidate.expires_at is None:
        return False
    expires = candidate.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def _seed_items(
    items: list[MediaItem],
    media_types: set[str],
    explicit_seed_ids: set[int] | None = None,
) -> list[MediaItem]:
    base_eligible = [
        item
        for item in items
        if item.media_type in media_types
        and item.user_state.status not in {"dropped", "hidden"}
    ]
    explicit_seed_ids = explicit_seed_ids or set()
    if explicit_seed_ids:
        explicit = [item for item in base_eligible if item.id in explicit_seed_ids]
        return sorted(explicit, key=lambda item: item.title.casefold())[:6]
    eligible = [item for item in base_eligible if item.tmdb_id]
    return sorted(
        eligible,
        key=lambda item: (
            item.user_state.user_rating is not None,
            item.user_state.user_rating or 0,
            item.user_state.priority == "high",
            item.imdb_rating or 0,
        ),
        reverse=True,
    )[:3]


def _genre_maps(
    tmdb: TmdbProvider, media_types: list[str]
) -> dict[str, dict[str, int]]:
    maps = {}
    for media_type in media_types:
        payload = tmdb.genre_list(media_type)
        maps[media_type] = {
            genre["name"].casefold(): int(genre["id"])
            for genre in payload.get("genres", [])
        }
    return maps


def _discover_params(
    request: LocalRecommendationRequest,
    media_type: str,
    genre_map: dict[str, int],
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "sort_by": (
            "vote_average.desc"
            if request.adventure == "safe"
            else "popularity.asc"
            if request.adventure == "adventurous"
            else "popularity.desc"
        ),
        "vote_count.gte": 100 if request.adventure == "safe" else 10,
    }
    genre_ids = [
        genre_map[name.casefold()]
        for name in request.genres
        if name.casefold() in genre_map
    ]
    if genre_ids and request.genre_mode == "require":
        params["with_genres"] = "|".join(str(value) for value in genre_ids)
    excluded_genre_ids = [
        genre_map[name.casefold()]
        for name in request.excluded_genres
        if name.casefold() in genre_map
    ]
    if excluded_genre_ids:
        params["without_genres"] = ",".join(str(value) for value in excluded_genre_ids)
    if request.runtime_max:
        params["with_runtime.lte"] = request.runtime_max
    if request.imdb_min:
        params["vote_average.gte"] = request.imdb_min
    if request.language:
        params["with_original_language"] = request.language
    if request.production_country:
        params["with_origin_country"] = request.production_country
    if request.release_year is not None and request.release_year_mode != "any":
        date_key = "first_air_date" if media_type == "tv" else "primary_release_date"
        if request.release_year_mode == "before":
            params[f"{date_key}.lte"] = f"{request.release_year - 1}-12-31"
        else:
            params[f"{date_key}.gte"] = f"{request.release_year + 1}-01-01"
    return params


def _candidate_cache(
    session: Session,
    media_type: str,
    payload: dict[str, Any],
    tmdb: TmdbProvider,
    omdb: OmdbProvider,
) -> DiscoveryCandidate:
    tmdb_id = int(payload["id"])
    candidate = session.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.tmdb_id == tmdb_id,
            DiscoveryCandidate.media_type == media_type,
        )
    )
    if candidate is not None and _not_expired(candidate):
        return candidate

    details = tmdb.details(media_type, tmdb_id)
    external_ids = tmdb.external_ids(media_type, tmdb_id)
    imdb_id = external_ids.get("imdb_id")
    omdb_payload: dict[str, Any] = {}
    if imdb_id:
        try:
            omdb_payload = omdb.by_imdb(imdb_id)
        except ProviderError:
            omdb_payload = {}
    is_tv = media_type == "tv"
    release_date = details.get("first_air_date" if is_tv else "release_date") or None
    runtime = (
        next(iter(details.get("episode_run_time") or []), None)
        if is_tv
        else details.get("runtime")
    )
    rt_rating = None
    for rating in omdb_payload.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            rt_rating = _number(rating.get("Value"))
    values = {
        "imdb_id": imdb_id,
        "title": details.get("name" if is_tv else "title") or "Untitled",
        "original_title": details.get("original_name" if is_tv else "original_title"),
        "release_date": release_date,
        "runtime_minutes": runtime,
        "genres_json": json.dumps(
            [genre["name"] for genre in details.get("genres", []) if genre.get("name")]
        ),
        "overview": details.get("overview") or None,
        "poster_url": (
            f"https://image.tmdb.org/t/p/w500{details['poster_path']}"
            if details.get("poster_path")
            else None
        ),
        "original_language": details.get("original_language"),
        "production_countries_json": json.dumps(
            [
                country["iso_3166_1"].upper()
                for country in details.get("production_countries", [])
                if country.get("iso_3166_1")
            ]
        ),
        "imdb_rating": _number(omdb_payload.get("imdbRating")),
        "rotten_tomatoes_rating": rt_rating,
        "tmdb_vote_average": _number(details.get("vote_average")),
        "tmdb_vote_count": details.get("vote_count"),
        "provider_payload_json": json.dumps(
            {"tmdb": details, "external_ids": external_ids, "omdb": omdb_payload},
            separators=(",", ":"),
            sort_keys=True,
        ),
        "fetched_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    if candidate is None:
        candidate = DiscoveryCandidate(
            tmdb_id=tmdb_id,
            media_type=media_type,
            **values,
        )
        session.add(candidate)
    else:
        for field, value in values.items():
            setattr(candidate, field, value)
    session.flush()
    return candidate


def _local_identity_sets(items: list[MediaItem]) -> tuple[set[tuple[str, int]], set[tuple]]:
    tmdb_ids = {
        (item.media_type, item.tmdb_id)
        for item in items
        if item.tmdb_id is not None
    }
    title_keys = {
        (item.media_type, item.normalized_title, item.start_year)
        for item in items
    }
    return tmdb_ids, title_keys


def _discovery_features(result: DiscoveryResultOut) -> SelectionFacets:
    return SelectionFacets(
        genres=frozenset(genre.casefold() for genre in result.genres),
        terms=frozenset(semantic_tokens(f"{result.title} {result.overview or ''}")),
        decade=result.year // 10 * 10 if result.year else None,
        language=result.original_language.casefold() if result.original_language else None,
        countries=frozenset(country.upper() for country in result.production_countries),
    )


def _diversify_results(
    ranked: list[DiscoveryResultOut],
    limit: int,
    adventure: str = "adjacent",
) -> list[DiscoveryResultOut]:
    selected: list[DiscoveryResultOut] = []
    remaining = list(ranked)
    features = {result.candidate_id: _discovery_features(result) for result in ranked}
    while remaining and len(selected) < limit:
        best: DiscoveryResultOut | None = None
        best_value = -1.0
        for result in remaining:
            current = features[result.candidate_id]
            max_similarity = 0.0
            for chosen in selected:
                previous = features[chosen.candidate_id]
                similarity = selection_similarity(current, previous)
                max_similarity = max(max_similarity, similarity)
            relevance = {"safe": 0.86, "adjacent": 0.75, "adventurous": 0.65}.get(
                adventure, 0.75
            )
            value = relevance * result.score - (1 - relevance) * max_similarity
            if value > best_value:
                best, best_value = result, value
        assert best is not None
        selected.append(best)
        remaining.remove(best)
    return selected


def discover_internet(
    session: Session,
    request: LocalRecommendationRequest,
    tmdb: TmdbProvider,
    omdb: OmdbProvider,
    *,
    search_queries: list[str] | None = None,
) -> InternetRecommendationResponse:
    items = list(
        session.scalars(
            select(MediaItem)
            .where(MediaItem.archived_at.is_(None))
            .options(
                selectinload(MediaItem.user_state),
                selectinload(MediaItem.tags).selectinload(MediaTag.tag),
                selectinload(MediaItem.watch_later_entry),
            )
        ).unique()
    )
    profile, taste_text, confidence = derive_taste_profile(items)
    media_types = (
        ["movie", "tv"] if request.media_type == "either" else [request.media_type]
    )
    genre_maps = _genre_maps(tmdb, media_types)
    seeds = _seed_items(items, set(media_types), set(request.seed_title_ids))
    raw: dict[tuple[str, int], dict[str, Any]] = {}
    resolved_seed_tmdb_ids: set[tuple[str, int]] = set()

    for seed in seeds:
        seed_tmdb_id = seed.tmdb_id
        seed_media_type = seed.media_type
        if seed_tmdb_id is None and seed.imdb_id:
            identity = tmdb.find_by_imdb(seed.imdb_id)
            identity_results = identity.get(
                "tv_results" if seed.media_type == "tv" else "movie_results"
            ) or []
            if identity_results:
                seed_tmdb_id = int(identity_results[0]["id"])
        if seed_tmdb_id is None:
            continue
        resolved_seed_tmdb_ids.add((seed_media_type, seed_tmdb_id))
        recommendations = tmdb.recommendations(seed_media_type, seed_tmdb_id)
        for payload in (recommendations.get("results") or [])[:12]:
            key = (seed_media_type, int(payload["id"]))
            entry = raw.setdefault(
                key, {"payload": payload, "seeds": set(), "queries": set(), "sources": set()}
            )
            entry["seeds"].add(seed.title)
            entry["sources"].add("seed similarity")
    for media_type in media_types:
        base_params = _discover_params(request, media_type, genre_maps[media_type])
        discovery_strategies = [
            ("criteria pool", base_params),
            (
                "quality pool",
                {**base_params, "sort_by": "vote_average.desc", "vote_count.gte": 50},
            ),
        ]
        for source, params in discovery_strategies:
            discovered = tmdb.discover(media_type, params)
            for payload in (discovered.get("results") or [])[:20]:
                key = (media_type, int(payload["id"]))
                entry = raw.setdefault(
                    key,
                    {"payload": payload, "seeds": set(), "queries": set(), "sources": set()},
                )
                entry["sources"].add(source)
    clean_search_queries: list[str] = []
    for query in (search_queries or [])[:6]:
        normalized_query = " ".join(query.split())[:80]
        if normalized_query and normalized_query.casefold() not in {
            existing.casefold() for existing in clean_search_queries
        }:
            clean_search_queries.append(normalized_query)
    for query in clean_search_queries:
        for media_type in media_types:
            searched = tmdb.search(media_type, query, None)
            for payload in (searched.get("results") or [])[:8]:
                key = (media_type, int(payload["id"]))
                entry = raw.setdefault(
                    key, {"payload": payload, "seeds": set(), "queries": set(), "sources": set()}
                )
                entry["queries"].add(query)
                entry["sources"].add("agent search")

    local_tmdb_ids, local_title_keys = _local_identity_sets(items)
    local_tmdb_ids.update(resolved_seed_tmdb_ids)
    dismissed = set(
        session.execute(
            select(DismissedDiscovery.media_type, DismissedDiscovery.tmdb_id)
        ).tuples()
    )
    filtered: list[tuple[str, dict[str, Any]]] = []
    for (media_type, tmdb_id), entry in raw.items():
        payload = entry["payload"]
        title = payload.get("name" if media_type == "tv" else "title") or ""
        date = payload.get("first_air_date" if media_type == "tv" else "release_date")
        title_key = (media_type, normalize_title(title), _year(date))
        candidate_year = _year(date)
        requested_genre_ids = {
            genre_maps[media_type][genre.casefold()]
            for genre in request.genres
            if genre.casefold() in genre_maps[media_type]
        }
        payload_genre_ids = {
            int(value) for value in (payload.get("genre_ids") or [])
        }
        excluded_genre_ids = {
            genre_maps[media_type][genre.casefold()]
            for genre in request.excluded_genres
            if genre.casefold() in genre_maps[media_type]
        }
        if (
            (media_type, tmdb_id) in local_tmdb_ids
            or title_key in local_title_keys
            or (media_type, tmdb_id) in dismissed
            or (
                request.genre_mode == "require"
                and requested_genre_ids
                and payload_genre_ids
                and not requested_genre_ids.intersection(payload_genre_ids)
            )
            or excluded_genre_ids.intersection(payload_genre_ids)
            or (
                request.release_year is not None
                and request.release_year_mode == "before"
                and candidate_year is not None
                and candidate_year >= request.release_year
            )
            or (
                request.release_year is not None
                and request.release_year_mode == "after"
                and candidate_year is not None
                and candidate_year <= request.release_year
            )
        ):
            continue
        filtered.append((media_type, entry))

    prompt = request_context_text(request)
    documents = [
        " ".join(
            [
                entry["payload"].get("name" if media_type == "tv" else "title") or "",
                entry["payload"].get("overview") or "",
            ]
        )
        for media_type, entry in filtered
    ]
    prompt_scores = semantic_cosines(documents, prompt)
    prelim = sorted(
        zip(filtered, prompt_scores),
        key=lambda pair: (
            len(pair[0][1]["seeds"]),
            pair[1],
            pair[0][1]["payload"].get("vote_average") or 0,
        ),
        reverse=True,
    )
    enrichment_limit = min(30, max(10, request.limit + 5))
    candidates: list[tuple[DiscoveryCandidate, set[str], float]] = []
    for ((media_type, entry), prompt_score) in prelim[:enrichment_limit]:
        candidate = _candidate_cache(
            session, media_type, entry["payload"], tmdb, omdb
        )
        candidate_year = _year(candidate.release_date)
        if (
            request.release_year is not None
            and request.release_year_mode == "before"
            and (candidate_year is None or candidate_year >= request.release_year)
        ):
            continue
        if (
            request.release_year is not None
            and request.release_year_mode == "after"
            and (candidate_year is None or candidate_year <= request.release_year)
        ):
            continue
        if request.runtime_max and (
            (request.strict_metadata and candidate.runtime_minutes is None)
            or (
                candidate.runtime_minutes is not None
                and candidate.runtime_minutes > request.runtime_max
            )
        ):
            continue
        if request.language and (candidate.original_language or "").casefold() != request.language:
            continue
        if request.production_country and request.production_country not in {
            country.upper() for country in item_production_countries(candidate)
        }:
            continue
        if request.imdb_min and (
            (request.strict_metadata and candidate.imdb_rating is None)
            or (
                candidate.imdb_rating is not None
                and candidate.imdb_rating < request.imdb_min
            )
        ):
            continue
        if request.rt_min and (
            (request.strict_metadata and candidate.rotten_tomatoes_rating is None)
            or (
                candidate.rotten_tomatoes_rating is not None
                and candidate.rotten_tomatoes_rating < request.rt_min
            )
        ):
            continue
        candidate_genres = {
            value.casefold()
            for value in json.loads(candidate.genres_json or "[]")
        }
        if candidate_genres.intersection(
            value.casefold() for value in request.excluded_genres
        ):
            continue
        if (
            request.genre_mode == "require"
            and request.genres
            and not candidate_genres.intersection(
                value.casefold() for value in request.genres
            )
        ):
                continue
        candidates.append((candidate, entry["seeds"], prompt_score))

    candidate_documents = [
        " ".join(
            [
                candidate.title,
                candidate.original_title or "",
                candidate.overview or "",
                *json.loads(candidate.genres_json or "[]"),
            ]
        )
        for candidate, _seed_titles, _prompt_score in candidates
    ]
    feedback_scores, feedback_count = feedback_preference_scores(
        session, candidate_documents
    )
    taste_scores = (
        semantic_cosines(candidate_documents, taste_text)
        if taste_text
        else [0.5] * len(candidate_documents)
    )
    results = []
    for index, (candidate, seed_titles, prompt_score) in enumerate(candidates):
        genres = json.loads(candidate.genres_json or "[]")
        requested_genres = {value.casefold() for value in request.genres}
        genre_match = (
            len(requested_genres.intersection(value.casefold() for value in genres))
            / len(requested_genres)
            if requested_genres
            else 0.5
        )
        ratings = [
            value
            for value in [
                candidate.imdb_rating / 10 if candidate.imdb_rating is not None else None,
                candidate.rotten_tomatoes_rating / 100
                if candidate.rotten_tomatoes_rating is not None
                else None,
                candidate.tmdb_vote_average / 10
                if candidate.tmdb_vote_average is not None
                else None,
            ]
            if value is not None
        ]
        rating_quality = sum(ratings) / len(ratings) if ratings else 0.4
        popularity = min(1.0, math.log10((candidate.tmdb_vote_count or 0) + 1) / 5)
        novelty = (
            popularity
            if request.adventure == "safe"
            else 1 - popularity
            if request.adventure == "adventurous"
            else 1 - abs(popularity - 0.5)
        )
        criteria_values = []
        if request.runtime_max:
            criteria_values.append(1.0)
        if request.imdb_min:
            criteria_values.append(1.0)
        if request.rt_min:
            criteria_values.append(1.0)
        if request.release_year is not None and request.release_year_mode != "any":
            criteria_values.append(1.0)
        if request.language:
            criteria_values.append(1.0)
        if request.production_country:
            criteria_values.append(1.0)
        criteria_values.extend([prompt_score, genre_match] if prompt else [genre_match])
        components = {
            "seed_similarity": min(1.0, len(seed_titles) / 2),
            "semantic_similarity": prompt_score if prompt else 0.5,
            "taste_similarity": taste_scores[index] if confidence != "low" else 0.5,
            "feedback_match": feedback_scores[index],
            "genre_keyword_match": (prompt_score + genre_match) / 2,
            "rating_quality": rating_quality,
            "criteria_match": sum(criteria_values) / len(criteria_values),
            "novelty": novelty,
            "metadata_quality": sum(
                value is not None
                for value in [
                    candidate.runtime_minutes,
                    candidate.overview,
                    candidate.poster_url,
                    candidate.imdb_id,
                ]
            )
            / 4,
        }
        breakdown = {
            name: round(value * INTERNET_WEIGHTS[name], 4)
            for name, value in components.items()
        }
        score = round(sum(breakdown.values()), 4)
        reasons = []
        if seed_titles:
            reasons.append(f"Recommended from: {', '.join(sorted(seed_titles)[:3])}")
        matched_queries = sorted(
            next(
                (
                    entry["queries"]
                    for candidate_media_type, entry in filtered
                    if candidate_media_type == candidate.media_type
                    and int(entry["payload"]["id"]) == candidate.tmdb_id
                ),
                set(),
            )
        )
        if matched_queries:
            reasons.append(f"Found by agent search: {matched_queries[0]}")
        retrieval_sources = sorted(
            next(
                (
                    entry["sources"]
                    for candidate_media_type, entry in filtered
                    if candidate_media_type == candidate.media_type
                    and int(entry["payload"]["id"]) == candidate.tmdb_id
                ),
                set(),
            )
        )
        if retrieval_sources and not seed_titles and not matched_queries:
            reasons.append(f"Retrieved from: {', '.join(retrieval_sources[:2])}")
        if prompt_score > 0.05:
            reasons.append("Its description matches your request")
        if request.runtime_max and candidate.runtime_minutes:
            reasons.append(
                f"{candidate.runtime_minutes} min, within your {request.runtime_max}-minute limit"
            )
        if request.release_year is not None and request.release_year_mode != "any":
            reasons.append(
                f"Released {request.release_year_mode} {request.release_year}"
            )
        if request.language:
            reasons.append(f"Original language: {request.language.upper()}")
        if request.production_country:
            reasons.append(f"Produced in {request.production_country}")
        if candidate.imdb_rating is not None:
            reasons.append(f"IMDb {candidate.imdb_rating:.1f}")
        if candidate.rotten_tomatoes_rating is not None:
            reasons.append(f"Rotten Tomatoes {candidate.rotten_tomatoes_rating:.0f}%")
        if not reasons:
            reasons.append("Strong provider and criteria fit")
        results.append(
            DiscoveryResultOut(
                candidate_id=candidate.id,
                tmdb_id=candidate.tmdb_id,
                media_type=candidate.media_type,
                imdb_id=candidate.imdb_id,
                title=candidate.title,
                year=_year(candidate.release_date),
                runtime_minutes=candidate.runtime_minutes,
                genres=genres,
                original_language=candidate.original_language,
                production_countries=item_production_countries(candidate),
                overview=candidate.overview,
                poster_url=candidate.poster_url,
                imdb_rating=candidate.imdb_rating,
                rotten_tomatoes_rating=candidate.rotten_tomatoes_rating,
                tmdb_vote_average=candidate.tmdb_vote_average,
                score=score,
                score_breakdown=breakdown,
                reasons=reasons[:4],
                seed_titles=sorted(seed_titles),
                tmdb_url=(
                    f"https://www.themoviedb.org/{'tv' if candidate.media_type == 'tv' else 'movie'}/{candidate.tmdb_id}"
                ),
            )
        )
    results.sort(key=lambda result: (-result.score, result.title))
    candidate_count = len(results)
    results = _diversify_results(results, request.limit, request.adventure)
    confidence_points = (
        (2 if len(seeds) >= 2 else 1 if seeds else 0)
        + (2 if feedback_count >= 10 else 1 if feedback_count >= 3 else 0)
        + (1 if candidate_count >= 5 else 0)
    )
    confidence = (
        "high" if confidence_points >= 4 else "medium" if confidence_points >= 2 else "low"
    )
    criteria = request.model_dump()
    recommendation_session = RecommendationSession(
        mode="internet",
        prompt=request.prompt,
        criteria_json=json.dumps(criteria, separators=(",", ":")),
        taste_profile_snapshot_json=json.dumps(
            {
                **profile,
                "seed_title_ids": [seed.id for seed in seeds],
                "retrieval_sources": ["seed similarity", "criteria pool", "quality pool", "agent search"],
            },
            separators=(",", ":"),
        ),
        results_json=json.dumps(
            [result.model_dump(mode="json") for result in results],
            separators=(",", ":"),
        ),
        confidence=confidence,
        candidate_count=candidate_count,
    )
    session.add(recommendation_session)
    session.commit()
    session.refresh(recommendation_session)
    return InternetRecommendationResponse(
        session_id=recommendation_session.id,
        mode="internet",
        confidence=confidence,
        candidate_count=candidate_count,
        criteria=criteria,
        results=results,
        search_queries=clean_search_queries,
    )


def add_discovery_to_library(
    session: Session, candidate_id: int
) -> tuple[MediaItem, bool]:
    candidate = session.get(DiscoveryCandidate, candidate_id)
    if candidate is None:
        raise LookupError("Discovery candidate not found")
    existing = session.scalar(
        select(MediaItem).where(
            or_(
                MediaItem.imdb_id == candidate.imdb_id
                if candidate.imdb_id
                else False,
                (
                    MediaItem.tmdb_id == candidate.tmdb_id
                )
                & (MediaItem.tmdb_media_type == candidate.media_type),
            )
        )
    )
    if existing is not None:
        return existing, False
    item = MediaItem(
        title=candidate.title,
        normalized_title=normalize_title(candidate.title),
        original_title=candidate.original_title,
        media_type=candidate.media_type,
        start_year=_year(candidate.release_date),
        release_date=candidate.release_date,
        runtime_minutes=candidate.runtime_minutes,
        genres_json=candidate.genres_json,
        overview=candidate.overview,
        poster_url=candidate.poster_url,
        original_language=candidate.original_language,
        production_countries_json=candidate.production_countries_json,
        imdb_id=candidate.imdb_id,
        imdb_rating=candidate.imdb_rating,
        rotten_tomatoes_rating=candidate.rotten_tomatoes_rating,
        tmdb_id=candidate.tmdb_id,
        tmdb_media_type=candidate.media_type,
        tmdb_vote_average=candidate.tmdb_vote_average,
        tmdb_vote_count=candidate.tmdb_vote_count,
        metadata_status="enriched",
        metadata_refreshed_at=candidate.fetched_at,
    )
    item.user_state = UserMediaState(status="want_to_watch", priority="normal")
    item.links.append(
        MediaLink(
            url=f"https://www.themoviedb.org/{'tv' if candidate.media_type == 'tv' else 'movie'}/{candidate.tmdb_id}",
            domain="themoviedb.org",
            link_type="metadata",
            original_label="internet discovery",
        )
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item, True
    item_production_countries,
    selection_similarity,
