from __future__ import annotations

import argparse
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.importer import normalize_title
from app.models import MediaItem, MediaLink, MediaTag, Tag, UserMediaState


IMDB_LIST_URL = "https://www.imdb.com/chart/top/"
RT_LIST_URL = "https://editorial.rottentomatoes.com/guide/best-movies-21st-century/"
IMDB_TAG = "imdb-top-250"
RT_TAG = "rt-best-21st-century"
IMDB_ID_RE = re.compile(r"/title/(tt\d+)/")


@dataclass(frozen=True)
class SourceEntry:
    source: str
    rank: int
    title: str
    year: int | None
    item_url: str
    list_url: str
    imdb_id: str | None = None
    rt_rating: float | None = None


@dataclass(frozen=True)
class ResolvedEntry:
    source: str
    rank: int
    title: str
    year: int | None
    item_url: str
    list_url: str
    imdb_id: str
    imdb_rating: float | None
    rt_rating: float | None
    metacritic_rating: float | None
    runtime_minutes: int | None
    genres: list[str]
    overview: str | None
    poster_url: str | None


def parse_imdb_json(path: Path) -> list[SourceEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries: list[SourceEntry] = []
    for row in payload:
        item_url = str(row["link"])
        match = IMDB_ID_RE.search(item_url)
        if not match:
            raise ValueError(f"IMDb row lacks a title ID: {item_url}")
        entries.append(
            SourceEntry(
                source="imdb",
                rank=int(row["Rank"]),
                title=str(row["name"]).strip(),
                year=None,
                item_url=item_url,
                list_url=IMDB_LIST_URL,
                imdb_id=match.group(1),
            )
        )
    if len(entries) != 250 or {entry.rank for entry in entries} != set(range(1, 251)):
        raise ValueError(f"Expected a complete IMDb Top 250; found {len(entries)} rows")
    return sorted(entries, key=lambda entry: entry.rank)


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", value)).split())


def parse_rt_html(path: Path) -> list[SourceEntry]:
    page = path.read_text(encoding="utf-8")
    starts = list(
        re.finditer(
            r'<div id="countdown-index-(\d+)" class="block-countdown rkv-block">',
            page,
        )
    )
    entries: list[SourceEntry] = []
    for index, start in enumerate(starts):
        block_end = starts[index + 1].start() if index + 1 < len(starts) else len(page)
        block = page[start.start() : block_end]
        title_match = re.search(
            r'<a class="meta-title" href="([^"]+)">(.*?)</a>\s*'
            r"<span class='meta-year'>\((\d{4})\)</span>",
            block,
            flags=re.DOTALL,
        )
        score_match = re.search(r'<span class="tMeterScore">(\d+)%</span>', block)
        if not title_match or not score_match:
            raise ValueError(f"Could not parse Rotten Tomatoes rank {start.group(1)}")
        entries.append(
            SourceEntry(
                source="rt",
                rank=int(start.group(1)),
                title=_plain_text(title_match.group(2)),
                year=int(title_match.group(3)),
                item_url=html.unescape(title_match.group(1)),
                list_url=RT_LIST_URL,
                rt_rating=float(score_match.group(1)),
            )
        )
    if len(entries) != 100 or {entry.rank for entry in entries} != set(range(1, 101)):
        raise ValueError(f"Expected the complete Rotten Tomatoes 100; found {len(entries)} rows")
    return sorted(entries, key=lambda entry: entry.rank)


def _number(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def _year(value: Any) -> int | None:
    match = re.search(r"\d{4}", str(value or ""))
    return int(match.group(0)) if match else None


def _runtime(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _omdb_request(api_key: str, entry: SourceEntry) -> dict[str, Any]:
    params: dict[str, Any] = {"apikey": api_key, "plot": "short", "type": "movie"}
    if entry.imdb_id:
        params["i"] = entry.imdb_id
    else:
        params["t"] = entry.title
        params["y"] = entry.year
    response = httpx.get("https://www.omdbapi.com/", params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("Response") == "False":
        raise ValueError(payload.get("Error", "OMDb title not found"))
    return payload


def _omdb_exact_title_fallback(api_key: str, entry: SourceEntry) -> dict[str, Any]:
    response = httpx.get(
        "https://www.omdbapi.com/",
        params={"apikey": api_key, "s": entry.title, "type": "movie"},
        timeout=20,
    )
    response.raise_for_status()
    candidates = [
        candidate
        for candidate in response.json().get("Search") or []
        if normalize_title(str(candidate.get("Title") or "")) == normalize_title(entry.title)
    ]
    if not candidates:
        raise ValueError("No exact-title OMDb fallback match")
    if entry.year:
        candidates.sort(
            key=lambda candidate: abs((_year(candidate.get("Year")) or 0) - entry.year)
        )
        candidate_year = _year(candidates[0].get("Year"))
        if candidate_year is None or abs(candidate_year - entry.year) > 2:
            raise ValueError("No exact-title OMDb fallback within two release years")
    imdb_id = candidates[0].get("imdbID")
    fallback = SourceEntry(
        source=entry.source,
        rank=entry.rank,
        title=entry.title,
        year=entry.year,
        item_url=entry.item_url,
        list_url=entry.list_url,
        imdb_id=imdb_id,
        rt_rating=entry.rt_rating,
    )
    return _omdb_request(api_key, fallback)


def _resolve_one(api_key: str, entry: SourceEntry) -> ResolvedEntry:
    try:
        payload = _omdb_request(api_key, entry)
        if (
            entry.source == "rt"
            and normalize_title(str(payload.get("Title") or ""))
            != normalize_title(entry.title)
        ):
            payload = _omdb_exact_title_fallback(api_key, entry)
    except Exception:
        if entry.source != "rt":
            raise
        payload = _omdb_exact_title_fallback(api_key, entry)
    imdb_id = payload.get("imdbID")
    if not isinstance(imdb_id, str) or not re.fullmatch(r"tt\d+", imdb_id):
        raise ValueError("OMDb response lacks a valid IMDb ID")
    if entry.imdb_id and imdb_id != entry.imdb_id:
        raise ValueError(f"IMDb ID mismatch: expected {entry.imdb_id}, got {imdb_id}")
    resolved_year = _year(payload.get("Year"))
    if entry.year and (
        resolved_year is None or abs(resolved_year - entry.year) > 2
    ):
        raise ValueError(f"Year mismatch: expected {entry.year}, got {resolved_year}")
    response_title = str(payload.get("Title") or entry.title).strip()
    if entry.source == "rt" and normalize_title(response_title) != normalize_title(entry.title):
        raise ValueError(f"Title mismatch: expected {entry.title}, got {response_title}")
    omdb_rt = None
    for rating in payload.get("Ratings") or []:
        if rating.get("Source") == "Rotten Tomatoes":
            omdb_rt = _number(rating.get("Value"))
            break
    poster = payload.get("Poster")
    return ResolvedEntry(
        source=entry.source,
        rank=entry.rank,
        title=response_title,
        year=entry.year if entry.source == "rt" else resolved_year,
        item_url=entry.item_url,
        list_url=entry.list_url,
        imdb_id=imdb_id,
        imdb_rating=_number(payload.get("imdbRating")),
        rt_rating=entry.rt_rating if entry.rt_rating is not None else omdb_rt,
        metacritic_rating=_number(payload.get("Metascore")),
        runtime_minutes=_runtime(payload.get("Runtime")),
        genres=[
            genre.strip()
            for genre in str(payload.get("Genre") or "").split(",")
            if genre.strip() and genre.strip() != "N/A"
        ],
        overview=None if payload.get("Plot") in (None, "", "N/A") else payload.get("Plot"),
        poster_url=None if poster in (None, "", "N/A") else str(poster),
    )


def resolve_sources(
    imdb_entries: list[SourceEntry],
    rt_entries: list[SourceEntry],
    output: Path,
    workers: int,
) -> None:
    api_key = get_settings().omdb_api_key
    if not api_key:
        raise RuntimeError("OMDB_API_KEY is not configured")
    entries = imdb_entries + rt_entries
    resolved: list[ResolvedEntry] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_entries = {
            executor.submit(_resolve_one, api_key, entry): entry for entry in entries
        }
        for completed, future in enumerate(as_completed(future_entries), start=1):
            entry = future_entries[future]
            try:
                resolved.append(future.result())
            except Exception as exc:
                failures.append(f"{entry.source} #{entry.rank} {entry.title}: {exc}")
            if completed % 25 == 0 or completed == len(entries):
                print(
                    f"resolved={len(resolved)} checked={completed}/{len(entries)} "
                    f"failed={len(failures)}",
                    flush=True,
                )
    output.write_text(
        json.dumps(
            {
                "entries": [asdict(entry) for entry in resolved],
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"snapshot={output}")
    if failures:
        print("\n".join(failures), file=sys.stderr)


def load_resolved(path: Path) -> tuple[list[ResolvedEntry], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ResolvedEntry(**entry) for entry in payload["entries"]], payload["failures"]


def _add_tag(session: Session, item: MediaItem, name: str) -> bool:
    tag = session.scalar(select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    if any(media_tag.tag_id == tag.id for media_tag in item.tags):
        return False
    item.tags.append(MediaTag(tag=tag))
    return True


def _add_link(
    item: MediaItem,
    url: str,
    label: str,
) -> bool:
    if any(link.url == url for link in item.links):
        return False
    hostname = urlparse(url).hostname or "unknown"
    item.links.append(
        MediaLink(
            url=url,
            domain=hostname.removeprefix("www."),
            link_type="source",
            original_label=label,
        )
    )
    return True


def analyze_or_apply(
    session: Session,
    entries: list[ResolvedEntry],
    *,
    apply: bool,
) -> dict[str, int]:
    items = list(session.scalars(select(MediaItem)))
    by_imdb = {item.imdb_id: item for item in items if item.imdb_id}
    by_title_year: dict[tuple[str, int | None], list[MediaItem]] = {}
    for item in items:
        by_title_year.setdefault((item.normalized_title, item.start_year), []).append(item)

    stats = {
        "source_rows": len(entries),
        "unique_source_titles": len({entry.imdb_id for entry in entries}),
        "existing_matches": 0,
        "new_titles": 0,
        "ambiguous": 0,
        "tags_added": 0,
        "links_added": 0,
    }
    seen_new: dict[str, MediaItem] = {}
    for entry in sorted(entries, key=lambda value: (value.source, value.rank)):
        item = by_imdb.get(entry.imdb_id) or seen_new.get(entry.imdb_id)
        if item is None:
            conflicts = by_title_year.get((normalize_title(entry.title), entry.year), [])
            if conflicts:
                stats["ambiguous"] += 1
                continue
            item = MediaItem(
                title=entry.title,
                normalized_title=normalize_title(entry.title),
                original_title=None,
                media_type="movie",
                start_year=entry.year,
                end_year=None,
                is_ongoing=False,
                runtime_minutes=entry.runtime_minutes,
                genres_json=json.dumps(entry.genres, ensure_ascii=False),
                overview=entry.overview,
                poster_url=entry.poster_url,
                imdb_id=entry.imdb_id,
                imdb_rating=entry.imdb_rating,
                rotten_tomatoes_rating=entry.rt_rating,
                metacritic_rating=entry.metacritic_rating,
                metadata_status="matched",
            )
            item.user_state = UserMediaState(status="want_to_watch", priority="normal")
            if apply:
                session.add(item)
                session.flush()
            seen_new[entry.imdb_id] = item
            stats["new_titles"] += 1
        elif entry.imdb_id not in seen_new:
            stats["existing_matches"] += 1

        tag_name = IMDB_TAG if entry.source == "imdb" else RT_TAG
        list_label = (
            f"IMDb Top 250 #{entry.rank}"
            if entry.source == "imdb"
            else f"RT 21st Century #{entry.rank}"
        )
        item_label = "IMDb" if entry.source == "imdb" else "Rotten Tomatoes"
        if apply:
            stats["tags_added"] += int(_add_tag(session, item, tag_name))
            stats["links_added"] += int(_add_link(item, entry.item_url, item_label))
            stats["links_added"] += int(_add_link(item, entry.list_url, list_label))
        else:
            current_tags = {media_tag.tag.name for media_tag in item.tags}
            current_links = {link.url for link in item.links}
            stats["tags_added"] += int(tag_name not in current_tags)
            stats["links_added"] += int(entry.item_url not in current_links)
            stats["links_added"] += int(entry.list_url not in current_links)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imdb-json", type=Path)
    parser.add_argument("--rt-html", type=Path)
    parser.add_argument("--resolved-json", type=Path, required=True)
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if args.resolve:
        if not args.imdb_json or not args.rt_html:
            parser.error("--resolve requires --imdb-json and --rt-html")
        resolve_sources(
            parse_imdb_json(args.imdb_json),
            parse_rt_html(args.rt_html),
            args.resolved_json,
            max(1, min(args.workers, 8)),
        )

    entries, failures = load_resolved(args.resolved_json)
    with SessionLocal() as session:
        stats = analyze_or_apply(session, entries, apply=args.commit)
        if args.commit:
            session.commit()
    print(json.dumps({"mode": "commit" if args.commit else "dry-run", **stats}, indent=2))
    if failures:
        print(f"unresolved={len(failures)}")


if __name__ == "__main__":
    main()
