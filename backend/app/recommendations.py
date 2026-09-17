from __future__ import annotations

import json
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    DiscoveryCandidate,
    DismissedRecommendation,
    MediaItem,
    MediaTag,
    RecommendationOutcome,
    RecommendationSession,
    TasteProfile,
    UserMediaState,
)
from .schemas import (
    LocalRecommendationRequest,
    LocalRecommendationResponse,
    RecommendationResultOut,
)


TOKEN_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "something",
    "movie",
    "show",
    "watch",
    "tonight",
}
SEMANTIC_CONCEPTS = {
    "light": {
        "light",
        "funny",
        "comedy",
        "comic",
        "charming",
        "warm",
        "uplifting",
        "hopeful",
        "playful",
        "feelgood",
        "easygoing",
    },
    "dark": {
        "dark",
        "bleak",
        "grim",
        "disturbing",
        "intense",
        "noir",
        "horror",
        "tragic",
        "brooding",
    },
    "relaxed": {
        "relaxed",
        "slow",
        "quiet",
        "gentle",
        "atmospheric",
        "meditative",
        "contemplative",
        "character",
        "intimate",
    },
    "fast": {
        "fast",
        "action",
        "kinetic",
        "thrilling",
        "thriller",
        "suspense",
        "heist",
        "adventure",
        "chase",
    },
    "cerebral": {
        "cerebral",
        "complex",
        "thoughtful",
        "philosophical",
        "mystery",
        "puzzle",
        "psychological",
        "mindbending",
        "identity",
    },
    "group": {
        "group",
        "crowd",
        "accessible",
        "entertaining",
        "ensemble",
        "fun",
        "spectacle",
    },
    "solo": {
        "solo",
        "subtle",
        "arthouse",
        "intimate",
        "cerebral",
        "contemplative",
        "complex",
    },
}
SEMANTIC_LOOKUP: dict[str, set[str]] = {}
for concept, terms in SEMANTIC_CONCEPTS.items():
    for term in terms:
        SEMANTIC_LOOKUP.setdefault(term, set()).add(concept)
WEIGHTS = {
    "semantic_similarity": 0.22,
    "taste_similarity": 0.15,
    "feedback_match": 0.10,
    "criteria_match": 0.16,
    "rating_quality": 0.15,
    "priority_status": 0.10,
    "novelty": 0.06,
    "context_fit": 0.06,
}


@dataclass
class ScoredItem:
    item: MediaItem
    genres: list[str]
    score: float
    breakdown: dict[str, float]
    reasons: list[str]


@dataclass(frozen=True)
class SelectionFacets:
    genres: frozenset[str]
    terms: frozenset[str]
    decade: int | None
    language: str | None
    countries: frozenset[str]


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def selection_similarity(left: SelectionFacets, right: SelectionFacets) -> float:
    """Compare candidates by stable facets instead of one flat bag of tokens."""
    weighted: list[tuple[float, float]] = []
    if left.genres and right.genres:
        weighted.append((0.35, _jaccard(left.genres, right.genres)))
    if left.terms and right.terms:
        weighted.append((0.35, _jaccard(left.terms, right.terms)))
    if left.decade is not None and right.decade is not None:
        weighted.append((0.10, float(left.decade == right.decade)))
    if left.language and right.language:
        weighted.append((0.10, float(left.language == right.language)))
    if left.countries and right.countries:
        weighted.append((0.10, _jaccard(left.countries, right.countries)))
    total_weight = sum(weight for weight, _value in weighted)
    return sum(weight * value for weight, value in weighted) / total_weight if total_weight else 0.0


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_RE.findall(text.casefold())
        if token not in STOPWORDS
    ]


def semantic_tokens(text: str) -> list[str]:
    tokens = tokenize(text)
    concepts = [
        f"concept_{concept}"
        for token in tokens
        for concept in SEMANTIC_LOOKUP.get(token, set())
    ]
    return [*tokens, *concepts, *concepts]


def semantic_cosines(documents: list[str], query: str) -> list[float]:
    """Blend lexical relevance with cached local semantic feature embeddings."""
    lexical = tfidf_cosines(documents, query)
    query_embedding = semantic_embedding(query)
    concepts: list[float] = []
    for document in documents:
        document_embedding = semantic_embedding(document)
        concepts.append(
            sum(
                left * right
                for left, right in zip(
                    document_embedding, query_embedding, strict=True
                )
            )
            if document_embedding and query_embedding
            else 0.0
        )
    return [
        min(1.0, lexical_score * 0.35 + concept_score * 0.65)
        for lexical_score, concept_score in zip(lexical, concepts, strict=True)
    ]


@lru_cache(maxsize=4096)
def semantic_embedding(text: str, dimensions: int = 256) -> tuple[float, ...]:
    if not text.strip():
        return ()
    vector = [0.0] * dimensions
    for token in semantic_tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return ()
    return tuple(value / norm for value in vector)


def request_context_text(request: LocalRecommendationRequest) -> str:
    values = [request.prompt or "", *request.genres]
    if request.tone != "any":
        values.append(request.tone)
    if request.pace != "any":
        values.append(request.pace)
    if request.company != "any":
        values.append(request.company)
    return " ".join(values)


def item_genres(item: MediaItem) -> list[str]:
    try:
        return list(json.loads(item.genres_json or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []


def item_production_countries(item: MediaItem | DiscoveryCandidate) -> list[str]:
    try:
        return list(json.loads(item.production_countries_json or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []


def item_tags(item: MediaItem) -> list[str]:
    return [media_tag.tag.name for media_tag in item.tags]


def item_document(item: MediaItem) -> str:
    return " ".join(
        [
            item.title,
            item.original_title or "",
            item.overview or "",
            *item_genres(item),
            *item_tags(item),
            item.user_state.notes or "",
        ]
    )


def tfidf_cosines(documents: list[str], query: str) -> list[float]:
    tokenized = [tokenize(document) for document in documents]
    query_tokens = tokenize(query)
    if not query_tokens:
        return [0.0] * len(documents)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized + [query_tokens]:
        document_frequency.update(set(tokens))
    document_count = len(tokenized) + 1

    def vector(tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        total = max(1, sum(counts.values()))
        return {
            token: (count / total)
            * (math.log((1 + document_count) / (1 + document_frequency[token])) + 1)
            for token, count in counts.items()
        }

    query_vector = vector(query_tokens)
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    scores = []
    for tokens in tokenized:
        doc_vector = vector(tokens)
        doc_norm = math.sqrt(sum(value * value for value in doc_vector.values()))
        if not doc_norm or not query_norm:
            scores.append(0.0)
            continue
        dot = sum(value * query_vector.get(token, 0.0) for token, value in doc_vector.items())
        scores.append(dot / (doc_norm * query_norm))
    return scores


def _taste_signal_weight(item: MediaItem) -> float:
    """Turn durable library behavior into an explicit, inspectable taste signal."""
    state = item.user_state
    rating = state.user_rating
    if rating is not None:
        if rating >= 9:
            return 1.25
        if rating >= 8:
            return 1.0
        if rating >= 7:
            return 0.75
        if rating <= 4:
            return -1.0
    if state.priority == "high":
        return 0.65
    if item.watch_later_entry is not None:
        return 0.55
    if state.status == "watched":
        return 0.2
    return 0.0


def derive_taste_profile(items: list[MediaItem]) -> tuple[dict[str, Any], str, str]:
    weighted = [(item, _taste_signal_weight(item)) for item in items]
    positives = [(item, weight) for item, weight in weighted if weight > 0]
    negatives = [(item, abs(weight)) for item, weight in weighted if weight < 0]
    genre_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    disliked_genres: Counter[str] = Counter()
    decade_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    for item, weight in positives:
        genre_counts.update({genre.casefold(): weight for genre in item_genres(item)})
        tag_counts.update({tag.casefold(): weight for tag in item_tags(item)})
        if item.start_year:
            decade_counts[f"{item.start_year // 10 * 10}s"] += weight
        if item.original_language:
            language_counts[item.original_language.casefold()] += weight
    for item, weight in negatives:
        disliked_genres.update({genre.casefold(): weight for genre in item_genres(item)})
    rating_count = sum(item.user_state.user_rating is not None for item in items)
    profile = {
        "liked_genres": [name for name, _ in genre_counts.most_common(8)],
        "disliked_genres": [name for name, _ in disliked_genres.most_common(5)],
        "liked_tags": [name for name, _ in tag_counts.most_common(10)],
        "preferred_decades": [name for name, _ in decade_counts.most_common(4)],
        "preferred_languages": [name for name, _ in language_counts.most_common(4)],
        "reference_title_ids": [item.id for item, _weight in positives[:20]],
        "negative_reference_title_ids": [item.id for item, _weight in negatives[:10]],
        "source_title_count": len(positives),
        "source_rating_count": rating_count,
        "signal_weight": round(sum(weight for _item, weight in positives), 2),
    }
    taste_text = " ".join(
        [
            *profile["liked_genres"],
            *profile["liked_tags"],
            *profile["preferred_decades"],
            *profile["preferred_languages"],
            *(
                item_document(item)
                for item, weight in positives[:20]
                for _ in range(max(1, round(weight * 3)))
            ),
        ]
    )
    if len(positives) >= 10 and rating_count >= 5:
        return profile, taste_text, "high"
    if len(positives) >= 5 or rating_count >= 3:
        return profile, taste_text, "medium"
    return profile, taste_text, "low"


def feedback_preference_scores(
    session: Session,
    documents: list[str],
) -> tuple[list[float], int]:
    positive_weights = {
        "selected": 2,
        "watched": 3,
        "liked": 4,
        "more_like_this": 4,
        "added": 2,
    }
    negative_weights = {
        "disliked": 4,
        "less_like_this": 3,
        "dismissed": 3,
        "not_interested": 4,
    }
    durable_actions = set(positive_weights) | set(negative_weights)
    outcomes = list(
        session.scalars(
            select(RecommendationOutcome).where(
                RecommendationOutcome.action.in_(durable_actions)
            )
        )
    )
    positive_documents: list[str] = []
    negative_documents: list[str] = []
    for outcome in outcomes:
        document = ""
        if outcome.media_item_id:
            item = session.get(MediaItem, outcome.media_item_id)
            if item is not None:
                document = item_document(item)
        if not document and outcome.discovery_candidate_id:
            candidate = session.get(DiscoveryCandidate, outcome.discovery_candidate_id)
            if candidate is not None:
                document = " ".join(
                    [
                        candidate.title,
                        candidate.original_title or "",
                        candidate.overview or "",
                        *json.loads(candidate.genres_json or "[]"),
                    ]
                )
        if not document:
            continue
        if outcome.action in positive_weights:
            positive_documents.extend([document] * positive_weights[outcome.action])
        else:
            negative_documents.extend([document] * negative_weights[outcome.action])
    low_rated_items = list(
        session.scalars(
            select(MediaItem)
            .join(UserMediaState)
            .where(UserMediaState.user_rating <= 4)
            .options(
                selectinload(MediaItem.tags).selectinload(MediaTag.tag),
                selectinload(MediaItem.user_state),
            )
        ).unique()
    )
    negative_documents.extend(
        item_document(item) for item in low_rated_items for _ in range(3)
    )
    positive_query = " ".join(positive_documents[-30:])
    negative_query = " ".join(negative_documents[-30:])
    positives = (
        semantic_cosines(documents, positive_query)
        if positive_query
        else [0.0] * len(documents)
    )
    negatives = (
        semantic_cosines(documents, negative_query)
        if negative_query
        else [0.0] * len(documents)
    )
    if not positive_documents and not negative_documents:
        return [0.5] * len(documents), 0
    return [
        max(0.0, min(1.0, 0.5 + positive * 0.6 - negative * 0.75))
        for positive, negative in zip(positives, negatives, strict=True)
    ], len(positive_documents) + len(negative_documents)


def candidate_items(
    session: Session, request: LocalRecommendationRequest
) -> tuple[list[MediaItem], list[MediaItem]]:
    options = (
        selectinload(MediaItem.user_state),
        selectinload(MediaItem.links),
        selectinload(MediaItem.tags).selectinload(MediaTag.tag),
        selectinload(MediaItem.watch_later_entry),
    )
    all_items = list(
        session.scalars(
            select(MediaItem)
            .where(MediaItem.archived_at.is_(None))
            .options(*options)
        ).unique()
    )
    dismissed_ids = set(session.scalars(select(DismissedRecommendation.media_item_id)))
    seed_ids = set(request.seed_title_ids)
    candidates = []
    requested_genres = {genre.casefold() for genre in request.genres}
    excluded_genres = {genre.casefold() for genre in request.excluded_genres}
    for item in all_items:
        state = item.user_state
        if (
            item.id in seed_ids
            or item.id in dismissed_ids
            or state.status not in {"want_to_watch", "maybe_later"}
        ):
            continue
        if request.media_type != "either" and item.media_type != request.media_type:
            continue
        if request.language and (item.original_language or "").casefold() != request.language:
            continue
        if request.production_country and request.production_country not in {
            country.upper() for country in item_production_countries(item)
        }:
            continue
        if (
            request.release_year is not None
            and request.release_year_mode == "before"
            and (item.start_year is None or item.start_year >= request.release_year)
        ):
            continue
        if (
            request.release_year is not None
            and request.release_year_mode == "after"
            and (item.start_year is None or item.start_year <= request.release_year)
        ):
            continue
        if request.runtime_max is not None and (
            (request.strict_metadata and item.runtime_minutes is None)
            or (item.runtime_minutes is not None and item.runtime_minutes > request.runtime_max)
        ):
            continue
        if request.imdb_min is not None and (
            (request.strict_metadata and item.imdb_rating is None)
            or (item.imdb_rating is not None and item.imdb_rating < request.imdb_min)
        ):
            continue
        if request.rt_min is not None and (
            (request.strict_metadata and item.rotten_tomatoes_rating is None)
            or (
                item.rotten_tomatoes_rating is not None
                and item.rotten_tomatoes_rating < request.rt_min
            )
        ):
            continue
        candidate_genres = {genre.casefold() for genre in item_genres(item)}
        if excluded_genres.intersection(candidate_genres):
            continue
        if (
            request.genre_mode == "require"
            and requested_genres
            and not requested_genres.intersection(candidate_genres)
        ):
            continue
        candidates.append(item)
    return all_items, candidates


def _quality(item: MediaItem) -> float:
    values = []
    if item.imdb_rating is not None:
        values.append(item.imdb_rating / 10)
    if item.rotten_tomatoes_rating is not None:
        values.append(item.rotten_tomatoes_rating / 100)
    if item.tmdb_vote_average is not None:
        values.append(item.tmdb_vote_average / 10)
    return sum(values) / len(values) if values else 0.45


def _priority_status(item: MediaItem) -> float:
    priority = {"high": 1.0, "normal": 0.62, "low": 0.3}.get(
        item.user_state.priority, 0.5
    )
    status_bonus = 0.1 if item.user_state.status == "want_to_watch" else 0.0
    return min(1.0, priority + status_bonus)


def _novelty(item: MediaItem, adventure: str) -> float:
    votes = item.tmdb_vote_count or 0
    popularity_proxy = min(1.0, math.log10(votes + 1) / 5)
    if adventure == "safe":
        return 0.4 * _quality(item) + 0.6 * popularity_proxy
    unusual = 1 - popularity_proxy
    if item.original_language and item.original_language != "en":
        unusual = min(1.0, unusual + 0.15)
    if adventure == "adventurous":
        return unusual
    return 1 - abs(popularity_proxy - 0.5)


def _context_fit(item: MediaItem, request: LocalRecommendationRequest) -> float:
    completeness = sum(
        value is not None
        for value in [item.runtime_minutes, item.overview, item.imdb_rating, item.poster_url]
    ) / 4
    if request.runtime_max and item.runtime_minutes:
        runtime_fit = max(0.0, 1 - item.runtime_minutes / request.runtime_max * 0.35)
        return (runtime_fit + completeness) / 2
    return completeness


def _weights_for_request(request: LocalRecommendationRequest, has_seeds: bool) -> dict[str, float]:
    weights = dict(WEIGHTS)
    if has_seeds:
        weights["taste_similarity"] += 0.08
        weights["semantic_similarity"] -= 0.04
        weights["priority_status"] -= 0.04
    if request.adventure == "safe":
        weights["rating_quality"] += 0.05
        weights["novelty"] -= 0.04
        weights["context_fit"] -= 0.01
    elif request.adventure == "adventurous":
        weights["novelty"] += 0.08
        weights["taste_similarity"] -= 0.04
        weights["rating_quality"] -= 0.04
    total = sum(weights.values())
    return {name: value / total for name, value in weights.items()}


def score_candidates(
    session: Session,
    candidates: list[MediaItem],
    request: LocalRecommendationRequest,
    taste_text: str,
    confidence: str,
    explicit_seed_text: str = "",
) -> list[ScoredItem]:
    documents = [item_document(item) for item in candidates]
    prompt_text = request_context_text(request)
    prompt_scores = semantic_cosines(documents, prompt_text)
    active_taste_text = explicit_seed_text or taste_text
    taste_scores = (
        semantic_cosines(documents, active_taste_text)
        if active_taste_text
        else [0.5] * len(candidates)
    )
    feedback_scores, _feedback_count = feedback_preference_scores(session, documents)
    requested_genres = {genre.casefold() for genre in request.genres}
    scored = []
    active_weights = _weights_for_request(request, bool(explicit_seed_text))
    for index, item in enumerate(candidates):
        genres = item_genres(item)
        genre_match = (
            len(
                requested_genres.intersection(genre.casefold() for genre in genres)
            )
            / len(requested_genres)
            if requested_genres
            else 0.5
        )
        active_criteria = [prompt_scores[index]] if prompt_text.strip() else []
        if requested_genres:
            active_criteria.append(genre_match)
        if request.runtime_max is not None:
            active_criteria.append(1.0)
        if request.imdb_min is not None:
            active_criteria.append(1.0)
        if request.rt_min is not None:
            active_criteria.append(1.0)
        if request.release_year is not None and request.release_year_mode != "any":
            active_criteria.append(1.0)
        if request.language is not None:
            active_criteria.append(1.0)
        if request.production_country is not None:
            active_criteria.append(1.0)
        criteria_match = (
            sum(active_criteria) / len(active_criteria) if active_criteria else 0.5
        )
        components = {
            "semantic_similarity": prompt_scores[index] if prompt_text.strip() else 0.5,
            "taste_similarity": (
                taste_scores[index]
                if explicit_seed_text or confidence != "low"
                else 0.5
            ),
            "feedback_match": feedback_scores[index],
            "criteria_match": criteria_match,
            "rating_quality": _quality(item),
            "priority_status": _priority_status(item),
            "novelty": _novelty(item, request.adventure),
            "context_fit": _context_fit(item, request),
        }
        weighted = {
            name: round(value * active_weights[name], 4) for name, value in components.items()
        }
        total = round(sum(weighted.values()), 4)
        reasons = []
        if requested_genres:
            matches = [
                genre
                for genre in genres
                if genre.casefold() in requested_genres
            ]
            if matches:
                reasons.append(f"Matches genre: {', '.join(matches)}")
        if request.runtime_max and item.runtime_minutes:
            reasons.append(
                f"{item.runtime_minutes} min, within your {request.runtime_max}-minute limit"
            )
        if request.release_year is not None and request.release_year_mode != "any":
            reasons.append(
                f"Released {request.release_year_mode} {request.release_year}"
            )
        if request.language:
            reasons.append(f"Original language: {request.language.upper()}")
        if request.production_country:
            reasons.append(f"Produced in {request.production_country}")
        if item.imdb_rating is not None:
            reasons.append(f"IMDb {item.imdb_rating:.1f}")
        if item.rotten_tomatoes_rating is not None:
            reasons.append(f"Rotten Tomatoes {item.rotten_tomatoes_rating:.0f}%")
        if item.user_state.priority == "high":
            reasons.append("You marked it high priority")
        if prompt_scores[index] > 0.08:
            reasons.append("Its description matches your request")
        if explicit_seed_text and taste_scores[index] > 0.08:
            reasons.append("Similar to your selected library titles")
        if not reasons:
            reasons.append("Strong overall fit among your unwatched titles")
        scored.append(
            ScoredItem(
                item=item,
                genres=genres,
                score=total,
                breakdown=weighted,
                reasons=reasons[:4],
            )
        )
    return sorted(scored, key=lambda result: (-result.score, result.item.title))


def _result_features(result: ScoredItem) -> SelectionFacets:
    item = result.item
    return SelectionFacets(
        genres=frozenset(genre.casefold() for genre in result.genres),
        terms=frozenset(semantic_tokens(item_document(item))),
        decade=item.start_year // 10 * 10 if item.start_year else None,
        language=item.original_language.casefold() if item.original_language else None,
        countries=frozenset(country.upper() for country in item_production_countries(item)),
    )


def diversify(
    scored: list[ScoredItem], limit: int, adventure: str = "adjacent"
) -> list[ScoredItem]:
    """MMR-style selection: retain relevance while avoiding near-duplicate choices."""
    selected: list[ScoredItem] = []
    remaining = list(scored)
    feature_cache = {result.item.id: _result_features(result) for result in scored}
    while remaining and len(selected) < limit:
        best: ScoredItem | None = None
        best_value = -1.0
        for result in remaining:
            features = feature_cache[result.item.id]
            max_similarity = 0.0
            for chosen in selected:
                chosen_features = feature_cache[chosen.item.id]
                similarity = selection_similarity(features, chosen_features)
                max_similarity = max(max_similarity, similarity)
            relevance = {"safe": 0.86, "adjacent": 0.75, "adventurous": 0.65}.get(
                adventure, 0.75
            )
            mmr = relevance * result.score - (1 - relevance) * max_similarity
            if mmr > best_value:
                best, best_value = result, mmr
        assert best is not None
        selected.append(best)
        remaining.remove(best)
    return selected


def recommend_local(
    session: Session, request: LocalRecommendationRequest
) -> LocalRecommendationResponse:
    all_items, candidates = candidate_items(session, request)
    profile, taste_text, confidence = derive_taste_profile(all_items)
    seed_ids = set(request.seed_title_ids)
    seed_items = [item for item in all_items if item.id in seed_ids]
    explicit_seed_text = " ".join(item_document(item) for item in seed_items)
    if seed_items:
        profile["explicit_seed_title_ids"] = [item.id for item in seed_items]
    scored = score_candidates(
        session,
        candidates,
        request,
        taste_text,
        confidence,
        explicit_seed_text,
    )
    selected = diversify(scored, request.limit, request.adventure)
    preference_actions = {
        "selected",
        "watched",
        "liked",
        "disliked",
        "more_like_this",
        "less_like_this",
        "dismissed",
        "not_interested",
        "added",
    }
    feedback_count = (
        session.scalar(
            select(func.count(RecommendationOutcome.id)).where(
                RecommendationOutcome.action.in_(preference_actions)
            )
        )
        or 0
    )
    profile["feedback_signal_count"] = feedback_count
    evidence_points = 0
    evidence_points += (
        2
        if profile["source_rating_count"] >= 5
        else 1
        if profile["source_rating_count"] >= 2
        else 0
    )
    evidence_points += (
        2
        if profile["source_title_count"] >= 10
        else 1
        if profile["source_title_count"] >= 4
        else 0
    )
    evidence_points += 2 if feedback_count >= 10 else 1 if feedback_count >= 3 else 0
    evidence_points += 2 if len(seed_items) >= 2 else 1 if seed_items else 0
    if len(scored) >= 2 and scored[0].score - scored[1].score >= 0.08:
        evidence_points += 1
    confidence = "high" if evidence_points >= 5 else "medium" if evidence_points >= 2 else "low"
    results = [
        RecommendationResultOut(
            title_id=result.item.id,
            title=result.item.title,
            media_type=result.item.media_type,
            year=result.item.start_year,
            runtime_minutes=result.item.runtime_minutes,
            genres=result.genres,
            original_language=result.item.original_language,
            production_countries=item_production_countries(result.item),
            poster_url=result.item.poster_url,
            imdb_id=result.item.imdb_id,
            imdb_rating=result.item.imdb_rating,
            rotten_tomatoes_rating=result.item.rotten_tomatoes_rating,
            status=result.item.user_state.status,
            priority=result.item.user_state.priority,
            watch_later=result.item.watch_later_entry is not None,
            score=result.score,
            score_breakdown=result.breakdown,
            reasons=result.reasons,
            links=[
                {"url": link.url, "domain": link.domain}
                for link in result.item.links
                if not link.archived
            ],
        )
        for result in selected
    ]
    criteria = request.model_dump()
    session.add(
        TasteProfile(
            profile_json=json.dumps(profile, separators=(",", ":")),
            source_title_count=profile["source_title_count"],
            source_rating_count=profile["source_rating_count"],
        )
    )
    recommendation_session = RecommendationSession(
        mode="local",
        prompt=request.prompt,
        criteria_json=json.dumps(criteria, separators=(",", ":")),
        taste_profile_snapshot_json=json.dumps(profile, separators=(",", ":")),
        results_json=json.dumps(
            [result.model_dump(mode="json") for result in results],
            separators=(",", ":"),
        ),
        confidence=confidence,
        candidate_count=len(candidates),
    )
    session.add(recommendation_session)
    session.commit()
    session.refresh(recommendation_session)
    confidence_reason = {
        "low": "Criteria-based: more ratings and Tonight feedback will improve personalization.",
        "medium": "Calibrated from your ratings, library signals, and recent Tonight feedback.",
        "high": "Strong evidence from your ratings, feedback, and a clearly separated shortlist.",
    }[confidence]
    if seed_items:
        confidence_reason = (
            f"Similarity is anchored to {len(seed_items)} title"
            f"{'s' if len(seed_items) != 1 else ''} selected from your library."
        )
    metadata_coverage = {
        "total": len(all_items),
        "runtime": sum(item.runtime_minutes is not None for item in all_items),
        "genres": sum(bool(item_genres(item)) for item in all_items),
        "overview": sum(bool(item.overview) for item in all_items),
    }
    return LocalRecommendationResponse(
        session_id=recommendation_session.id,
        mode="local",
        confidence=confidence,
        confidence_reason=confidence_reason,
        candidate_count=len(candidates),
        metadata_coverage=metadata_coverage,
        criteria=criteria,
        results=results,
    )
