from __future__ import annotations

from collections import defaultdict
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, object_session, selectinload

from .importer import (
    ParsedRow,
    file_digest,
    infer_media_type,
    normalize_title,
    parse_catalog,
    parse_year,
    source_domain,
)
from .models import (
    ImportJob,
    ImportRow,
    MediaItem,
    MediaLink,
    MediaTag,
    Tag,
    UserMediaState,
)
from .metadata import manual_fields
from .schemas import TitleDetail, TitleSummary


def preview_import(session: Session, source_path: Path) -> ImportJob:
    parsed = parse_catalog(source_path)
    groups: dict[str, list[ParsedRow]] = defaultdict(list)
    for row in parsed:
        if row.imdb_id:
            groups[row.imdb_id].append(row)

    duplicate_rows = sum(len(rows) - 1 for rows in groups.values() if len(rows) > 1)
    review_rows = sum(1 for row in parsed if not row.imdb_id)
    job = ImportJob(
        source_path=str(source_path),
        source_digest=file_digest(source_path),
        total_rows=len(parsed),
        matched_rows=len(parsed) - review_rows,
        duplicate_rows=duplicate_rows,
        review_rows=review_rows,
    )
    session.add(job)
    session.flush()

    for row in parsed:
        job.rows.append(
            ImportRow(
                row_number=row.row_number,
                raw_title=row.title,
                normalized_title=row.normalized_title,
                raw_year=row.raw_year,
                raw_section=row.section,
                raw_url=row.source_url,
                imdb_id=row.imdb_id,
                imdb_rating=row.imdb_rating,
                rt_rating=row.rt_rating,
                match_status=row.match_status,
                proposed_action="merge" if row.imdb_id and len(groups[row.imdb_id]) > 1 else (
                    "create" if row.imdb_id else "review"
                ),
                confidence=1.0 if row.imdb_id else 0.0,
                resolution_status="pending" if not row.imdb_id else "proposed",
            )
        )
    session.commit()
    session.refresh(job)
    return job


def commit_import(session: Session, job: ImportJob) -> ImportJob:
    if job.status == "committed":
        return job
    parsed_rows = [
        ParsedRow(
            row_number=row.row_number,
            title=row.raw_title,
            normalized_title=row.normalized_title,
            raw_year=row.raw_year,
            section=row.raw_section,
            imdb_id=row.imdb_id,
            imdb_rating=row.imdb_rating,
            rt_rating=row.rt_rating,
            source_url=row.raw_url,
            match_status=row.match_status,
        )
        for row in job.rows
    ]
    by_imdb: dict[str, list[ParsedRow]] = defaultdict(list)
    for row in parsed_rows:
        if row.imdb_id:
            by_imdb[row.imdb_id].append(row)

    import_row_by_number = {row.row_number: row for row in job.rows}
    for imdb_id, rows in by_imdb.items():
        item = session.scalar(
            select(MediaItem)
            .where(MediaItem.imdb_id == imdb_id)
            .options(selectinload(MediaItem.links), selectinload(MediaItem.user_state))
        )
        representative = rows[0]
        if item is None:
            start_year, end_year, ongoing = parse_year(representative.raw_year)
            item = MediaItem(
                title=representative.title,
                normalized_title=representative.normalized_title,
                original_title=representative.title,
                media_type=infer_media_type(rows),
                start_year=start_year,
                end_year=end_year,
                is_ongoing=ongoing,
                imdb_id=imdb_id,
                imdb_rating=representative.imdb_rating,
                rotten_tomatoes_rating=representative.rt_rating,
                metadata_status="matched",
            )
            item.user_state = UserMediaState(status="want_to_watch", priority="normal")
            session.add(item)
            session.flush()
        existing_urls = {link.url for link in item.links}
        for row in rows:
            if row.source_url and row.source_url not in existing_urls:
                item.links.append(
                    MediaLink(
                        url=row.source_url,
                        domain=source_domain(row.source_url),
                        link_type="source",
                        original_label="bookmark",
                    )
                )
                existing_urls.add(row.source_url)
            import_row = import_row_by_number[row.row_number]
            import_row.resolved_media_item_id = item.id
            import_row.resolution_status = "merged" if len(rows) > 1 else "created"

    job.status = "committed"
    job.committed_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(job)
    return job


def tags_for(item: MediaItem) -> list[str]:
    return sorted(media_tag.tag.name for media_tag in item.tags)


def title_summary(item: MediaItem) -> TitleSummary:
    state = item.user_state
    return TitleSummary(
        id=item.id,
        title=item.title,
        media_type=item.media_type,
        start_year=item.start_year,
        end_year=item.end_year,
        is_ongoing=item.is_ongoing,
        imdb_id=item.imdb_id,
        imdb_rating=item.imdb_rating,
        rotten_tomatoes_rating=item.rotten_tomatoes_rating,
        poster_url=item.poster_url,
        metadata_status=item.metadata_status,
        status=state.status,
        priority=state.priority,
        user_rating=state.user_rating,
        link_count=sum(1 for link in item.links if not link.archived),
        tags=tags_for(item),
        genres=json.loads(item.genres_json or "[]"),
        watch_later=item.watch_later_entry is not None,
    )


def title_detail(item: MediaItem) -> TitleDetail:
    summary = title_summary(item).model_dump()
    return TitleDetail(
        **summary,
        original_title=item.original_title,
        runtime_minutes=item.runtime_minutes,
        release_date=item.release_date,
        original_language=item.original_language,
        overview=item.overview,
        metacritic_rating=item.metacritic_rating,
        tmdb_vote_average=item.tmdb_vote_average,
        tmdb_vote_count=item.tmdb_vote_count,
        metadata_refreshed_at=item.metadata_refreshed_at,
        manual_fields=sorted(manual_fields(object_session(item), item.id)),
        notes=item.user_state.notes,
        links=[link for link in item.links if not link.archived],
    )


def title_query(
    session: Session,
    *,
    q: str | None,
    media_type: str | None,
    status: str | None,
    year_min: int | None,
    year_max: int | None,
    imdb_min: float | None,
    rt_min: float | None,
    sort: str,
):
    stmt = (
        select(MediaItem)
        .join(MediaItem.user_state)
        .where(MediaItem.archived_at.is_(None))
        .options(
            selectinload(MediaItem.links),
            selectinload(MediaItem.user_state),
            selectinload(MediaItem.tags).selectinload(MediaTag.tag),
            selectinload(MediaItem.watch_later_entry),
        )
    )
    if q:
        term = f"%{q.casefold()}%"
        matching_tag_items = (
            select(MediaTag.media_item_id)
            .join(Tag, Tag.id == MediaTag.tag_id)
            .where(func.lower(Tag.name).like(term))
        )
        stmt = stmt.where(
            or_(
                func.lower(MediaItem.title).like(term),
                func.lower(func.coalesce(UserMediaState.notes, "")).like(term),
                MediaItem.id.in_(matching_tag_items),
            )
        )
    if media_type and media_type != "all":
        stmt = stmt.where(MediaItem.media_type == media_type)
    if status and status != "all":
        stmt = stmt.where(UserMediaState.status == status)
    if year_min is not None:
        stmt = stmt.where(MediaItem.start_year >= year_min)
    if year_max is not None:
        stmt = stmt.where(MediaItem.start_year <= year_max)
    if imdb_min is not None:
        stmt = stmt.where(MediaItem.imdb_rating >= imdb_min)
    if rt_min is not None:
        stmt = stmt.where(MediaItem.rotten_tomatoes_rating >= rt_min)

    active_link_count = (
        select(func.count(MediaLink.id))
        .where(
            MediaLink.media_item_id == MediaItem.id,
            MediaLink.archived.is_(False),
        )
        .correlate(MediaItem)
        .scalar_subquery()
    )
    priority_rank = case(
        (UserMediaState.priority == "high", 3),
        (UserMediaState.priority == "normal", 2),
        (UserMediaState.priority == "low", 1),
        else_=0,
    )
    sort_expressions = {
        "title": func.lower(MediaItem.title),
        "type": MediaItem.media_type,
        "year": MediaItem.start_year,
        "imdb": MediaItem.imdb_rating,
        "rt": MediaItem.rotten_tomatoes_rating,
        "status": UserMediaState.status,
        "priority": priority_rank,
        "sources": active_link_count,
        "genre": func.lower(MediaItem.genres_json),
    }
    legacy_sorts = {
        "title": ("title", "asc"),
        "year_desc": ("year", "desc"),
        "imdb_desc": ("imdb", "desc"),
        "updated_desc": (None, "desc"),
        "priority": ("priority", "desc"),
    }
    if sort in legacy_sorts:
        sort_key, direction = legacy_sorts[sort]
    else:
        sort_key, _, direction = sort.rpartition("_")
        if direction not in {"asc", "desc"}:
            sort_key, direction = "title", "asc"

    if sort_key is None:
        order = MediaItem.updated_at.desc()
    else:
        expression = sort_expressions.get(sort_key, sort_expressions["title"])
        order = (
            expression.desc().nullslast()
            if direction == "desc"
            else expression.asc().nullslast()
        )
    return stmt.order_by(order, func.lower(MediaItem.title).asc(), MediaItem.id)


def replace_tags(session: Session, item: MediaItem, names: list[str]) -> None:
    clean_names = sorted({name.strip().casefold() for name in names if name.strip()})
    item.tags.clear()
    session.flush()
    for name in clean_names:
        tag = session.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        item.tags.append(MediaTag(tag=tag))
