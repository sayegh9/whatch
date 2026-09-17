from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


IMDB_RE = re.compile(r"tt\d+")
URL_RE = re.compile(r"https?://[^)]+")
YEAR_RE = re.compile(r"^(\d{4})(?:\s*[–-]\s*(\d{4})?)?$")


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    title: str
    normalized_title: str
    raw_year: str | None
    section: str
    imdb_id: str | None
    imdb_rating: float | None
    rt_rating: float | None
    source_url: str | None
    match_status: str


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^\w]+", " ", normalized.casefold())
    return " ".join(normalized.split())


def split_markdown_row(line: str) -> list[str]:
    content = line.strip()[1:-1]
    fields = re.split(r"(?<!\\)\|", content)
    return [field.strip().replace(r"\|", "|") for field in fields]


def parse_optional_rating(value: str, suffix: str) -> float | None:
    if value == "N/A":
        return None
    try:
        return float(value.removesuffix(suffix).strip())
    except ValueError:
        return None


def parse_catalog(path: Path) -> list[ParsedRow]:
    section: str | None = None
    parsed: list[ParsedRow] = []
    for row_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line == "## Movies":
            section = "movie"
            continue
        if line == "## TV Series":
            section = "tv"
            continue
        if line == "## Unmatched / Needs Manual Review":
            break
        if section not in {"movie", "tv"} or not line.startswith("|"):
            continue
        if re.fullmatch(r"\|[-:| ]+\|", line):
            continue
        fields = split_markdown_row(line)
        if not fields or fields[0] == "Title" or len(fields) < 7:
            continue
        imdb_match = IMDB_RE.search(fields[2])
        source_match = URL_RE.search(fields[5])
        parsed.append(
            ParsedRow(
                row_number=row_number,
                title=fields[0],
                normalized_title=normalize_title(fields[0]),
                raw_year=None if fields[1] == "N/A" else fields[1],
                section=section,
                imdb_id=imdb_match.group(0) if imdb_match else None,
                imdb_rating=parse_optional_rating(fields[3], "/10"),
                rt_rating=parse_optional_rating(fields[4], "%"),
                source_url=source_match.group(0) if source_match else None,
                match_status=fields[6],
            )
        )
    return parsed


def parse_year(value: str | None) -> tuple[int | None, int | None, bool]:
    if not value:
        return None, None, False
    match = YEAR_RE.fullmatch(value)
    if not match:
        return None, None, False
    start = int(match.group(1))
    has_range = "–" in value or "-" in value
    end = int(match.group(2)) if match.group(2) else None
    return start, end, has_range and end is None


def infer_media_type(rows: list[ParsedRow]) -> str:
    tv_hints = 0
    movie_hints = 0
    for row in rows:
        if row.section == "tv":
            tv_hints += 2
        else:
            movie_hints += 1
        if row.source_url:
            path = urlparse(row.source_url).path.casefold()
            if re.search(r"/(tv|watch-tv|watchseries|episode)\b", path):
                tv_hints += 3
            elif re.search(r"/(movie|watch-movie)\b", path):
                movie_hints += 2
    return "tv" if tv_hints > movie_hints else "movie"


def source_domain(url: str) -> str:
    return urlparse(url).hostname.removeprefix("www.") if urlparse(url).hostname else "unknown"


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

