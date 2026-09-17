from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import ImportJob, ImportRow, MediaItem, MediaLink, UserMediaState
from backend.app.services import (
    commit_import,
    preview_import,
    replace_tags,
    title_detail,
    title_query,
)


SOURCE = Path(__file__).resolve().parents[2] / "bookmark_movies_tv_series_with_ratings.md"


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def test_preview_reports_real_catalog_shape(session: Session) -> None:
    job = preview_import(session, SOURCE)

    assert job.total_rows == 324
    assert job.matched_rows == 312
    assert job.duplicate_rows == 23
    assert job.review_rows == 12
    assert len(job.rows) == 324


def test_commit_deduplicates_identity_and_preserves_links(session: Session) -> None:
    preview = preview_import(session, SOURCE)
    job = session.scalar(select(ImportJob).where(ImportJob.id == preview.id))
    assert job is not None

    commit_import(session, job)

    assert session.scalar(select(func.count(MediaItem.id))) == 289
    assert session.scalar(select(func.count(MediaLink.id))) == 312
    assert session.scalar(
        select(func.count(ImportRow.id)).where(ImportRow.resolution_status == "pending")
    ) == 12
    assert session.scalar(
        select(func.count(UserMediaState.media_item_id)).where(
            UserMediaState.status == "want_to_watch"
        )
    ) == 289

    knick = session.scalar(select(MediaItem).where(MediaItem.imdb_id == "tt2937900"))
    assert knick is not None
    assert knick.media_type == "tv"
    assert session.scalar(
        select(func.count(MediaLink.id)).where(MediaLink.media_item_id == knick.id)
    ) == 3

    detail = title_detail(knick)
    assert detail.id == knick.id
    assert detail.poster_url == knick.poster_url
    assert len(detail.links) == 3


def test_reimport_is_idempotent(session: Session) -> None:
    first = preview_import(session, SOURCE)
    first_job = session.scalar(select(ImportJob).where(ImportJob.id == first.id))
    assert first_job is not None
    commit_import(session, first_job)

    second = preview_import(session, SOURCE)
    second_job = session.scalar(select(ImportJob).where(ImportJob.id == second.id))
    assert second_job is not None
    commit_import(session, second_job)

    assert session.scalar(select(func.count(MediaItem.id))) == 289
    assert session.scalar(select(func.count(MediaLink.id))) == 312


def test_catalog_search_includes_normalized_tags(session: Session) -> None:
    preview = preview_import(session, SOURCE)
    job = session.scalar(select(ImportJob).where(ImportJob.id == preview.id))
    assert job is not None
    commit_import(session, job)
    knick = session.scalar(select(MediaItem).where(MediaItem.imdb_id == "tt2937900"))
    assert knick is not None
    replace_tags(session, knick, ["medical drama", "period piece"])
    session.commit()

    results = session.scalars(
        title_query(
            session,
            q="medical drama",
            media_type=None,
            status=None,
            year_min=None,
            year_max=None,
            imdb_min=None,
            rt_min=None,
            sort="title",
        )
    ).all()

    assert [item.imdb_id for item in results] == ["tt2937900"]


def test_catalog_supports_every_column_sort(session: Session) -> None:
    fixtures = [
        MediaItem(
            title="Sort Fixture Alpha",
            normalized_title="sort fixture alpha",
            media_type="movie",
            start_year=2001,
            imdb_rating=7.0,
            rotten_tomatoes_rating=70,
            genres_json='["Action"]',
            user_state=UserMediaState(status="watched", priority="low"),
        ),
        MediaItem(
            title="Sort Fixture Beta",
            normalized_title="sort fixture beta",
            media_type="tv",
            start_year=2002,
            imdb_rating=8.0,
            rotten_tomatoes_rating=80,
            genres_json='["Comedy"]',
            user_state=UserMediaState(status="want_to_watch", priority="high"),
        ),
        MediaItem(
            title="Sort Fixture Gamma",
            normalized_title="sort fixture gamma",
            media_type="movie",
            start_year=2003,
            imdb_rating=9.0,
            rotten_tomatoes_rating=90,
            genres_json='["Drama"]',
            user_state=UserMediaState(status="dropped", priority="normal"),
        ),
    ]
    for index, item in enumerate(fixtures, start=1):
        for link_index in range(index):
            item.links.append(
                MediaLink(
                    url=f"https://example.com/{index}/{link_index}",
                    domain="example.com",
                    link_type="source",
                )
            )
    session.add_all(fixtures)
    session.commit()

    expected = {
        "title_asc": ["Alpha", "Beta", "Gamma"],
        "title_desc": ["Gamma", "Beta", "Alpha"],
        "type_asc": ["Alpha", "Gamma", "Beta"],
        "year_desc": ["Gamma", "Beta", "Alpha"],
        "imdb_desc": ["Gamma", "Beta", "Alpha"],
        "rt_desc": ["Gamma", "Beta", "Alpha"],
        "status_asc": ["Gamma", "Beta", "Alpha"],
        "priority_desc": ["Beta", "Gamma", "Alpha"],
        "sources_desc": ["Gamma", "Beta", "Alpha"],
        "genre_asc": ["Alpha", "Beta", "Gamma"],
    }

    for sort, suffixes in expected.items():
        results = session.scalars(
            title_query(
                session,
                q="sort fixture",
                media_type=None,
                status=None,
                year_min=None,
                year_max=None,
                imdb_min=None,
                rt_min=None,
                sort=sort,
            )
        ).all()
        assert [item.title.rsplit(" ", 1)[-1] for item in results] == suffixes
