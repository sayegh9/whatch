from __future__ import annotations

import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.main import (
    add_discovery_to_watch_later,
    add_title_to_watch_later,
    list_watch_later,
    move_watch_later_to_library,
    remove_title_from_watch_later,
)
from backend.app.models import (
    DiscoveryCandidate,
    MediaItem,
    UserMediaState,
    WatchLaterEntry,
)
from backend.app.schemas import WatchLaterMoveRequest


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_watch_later_is_durable_ordered_and_idempotent():
    with make_session() as session:
        item = MediaItem(
            title="Queue Me",
            normalized_title="queue me",
            media_type="movie",
            genres_json=json.dumps(["Drama"]),
        )
        item.user_state = UserMediaState(status="want_to_watch", priority="normal")
        session.add(item)
        session.commit()

        first = add_title_to_watch_later(item.id, session)
        second = add_title_to_watch_later(item.id, session)
        queue = list_watch_later(session)

        assert first.watch_later is True
        assert second.watch_later is True
        assert queue.total == 1
        assert queue.items[0].id == item.id
        assert queue.items[0].watch_later is True
        assert session.scalar(select(func.count(WatchLaterEntry.id))) == 1

        remove_title_from_watch_later(item.id, session)

        assert list_watch_later(session).total == 0


def test_online_recommendation_can_be_added_directly_to_watch_later():
    with make_session() as session:
        candidate = DiscoveryCandidate(
            tmdb_id=404,
            media_type="movie",
            imdb_id="tt0404000",
            title="Online Queue",
            release_date="2025-01-02",
            runtime_minutes=101,
            genres_json=json.dumps(["Mystery"]),
            overview="A new mystery.",
            provider_payload_json="{}",
        )
        session.add(candidate)
        session.commit()

        detail = add_discovery_to_watch_later(candidate.id, session)
        queue = list_watch_later(session)

        assert detail.watch_later is True
        assert queue.total == 1
        assert queue.items[0].title == "Online Queue"
        assert queue.items[0].status == "want_to_watch"


def test_watch_later_can_move_to_library_and_record_watched_status():
    with make_session() as session:
        item = MediaItem(
            title="Finished Queue",
            normalized_title="finished queue",
            media_type="movie",
            genres_json="[]",
        )
        item.user_state = UserMediaState(status="want_to_watch", priority="normal")
        session.add(item)
        session.commit()
        add_title_to_watch_later(item.id, session)

        moved = move_watch_later_to_library(
            item.id,
            WatchLaterMoveRequest(watched=True),
            session,
        )

        assert moved.status == "watched"
        assert moved.watch_later is False
        assert session.get(MediaItem, item.id) is not None
        assert list_watch_later(session).total == 0
