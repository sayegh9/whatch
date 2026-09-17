from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseModel):
    database_url: str
    catalog_source: Path
    tmdb_api_token: str | None
    omdb_api_key: str | None
    gemini_api_key: str | None
    gemini_enabled: bool = False
    gemini_model: str = "gemini-3.6-flash"
    metadata_language: str = "en-US"
    poster_directory: Path


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    database_url = os.getenv(
        "WHATCH_DATABASE_URL",
        f"sqlite:///{PROJECT_ROOT / 'data' / 'whatch.db'}",
    )
    source = Path(
        os.getenv(
            "WHATCH_CATALOG_SOURCE",
            str(PROJECT_ROOT / "bookmark_movies_tv_series_with_ratings.md"),
        )
    ).resolve()
    return Settings(
        database_url=database_url,
        catalog_source=source,
        tmdb_api_token=os.getenv("TMDB_API_TOKEN"),
        omdb_api_key=os.getenv("OMDB_API_KEY"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        gemini_enabled=_enabled(os.getenv("WHATCH_GEMINI_ENABLED")),
        gemini_model=os.getenv("WHATCH_GEMINI_MODEL", "gemini-3.6-flash"),
        metadata_language=os.getenv("WHATCH_METADATA_LANGUAGE", "en-US"),
        poster_directory=Path(
            os.getenv("WHATCH_POSTER_DIRECTORY", str(PROJECT_ROOT / "data" / "posters"))
        ).resolve(),
    )
