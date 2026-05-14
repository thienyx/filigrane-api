from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.models.entities import Follow, Pin, Source, User
from filigrane_api.services.comments_ops import fetch_comment_thread


@dataclass(slots=True)
class FeedCursor:
    anchored: datetime
    pin_identifier: int


def encode_feed_cursor(moment: datetime, pin_identifier: int) -> str:
    return f"{moment.timestamp()}:{pin_identifier}"


def decode_feed_cursor(token: str) -> FeedCursor | None:
    head, tail = token.split(":", maxsplit=1)
    try:
        anchored = datetime.fromtimestamp(float(head), tz=UTC)
        pin_identifier = int(tail)
    except ValueError:
        return None
    return FeedCursor(anchored=anchored, pin_identifier=pin_identifier)


async def followed_actor_ids(session: AsyncSession, viewer_pk: int) -> list[int]:
    stmt = select(Follow.followee_id).where(Follow.follower_id == viewer_pk)
    rows = await session.scalars(stmt)
    return sorted({int(pk) for pk in rows.all()})


async def collect_feed_pins(
    session: AsyncSession,
    *,
    viewer_pk: int,
    slice_size: int,
    navigator: FeedCursor | None,
) -> tuple[list[tuple[Pin, Source, User]], str | None]:
    actors = await followed_actor_ids(session, viewer_pk)
    if not actors:
        return [], None

    stmt: Select[tuple[Pin, Source, User]] = (
        select(Pin, Source, User)
        .join(Source, Pin.source_id == Source.id)
        .join(User, Pin.user_id == User.id)
        .where(Pin.user_id.in_(actors))
    )
    if navigator is not None:
        stmt = stmt.where(
            tuple_(Pin.created_at, Pin.id)
            < tuple_(navigator.anchored, navigator.pin_identifier),
        )

    stmt = stmt.order_by(
        Pin.created_at.desc(),
        Pin.id.desc(),
    ).limit(slice_size + 1)

    page = await session.execute(stmt)
    rows = page.all()

    page_rows = rows[:slice_size]

    hydrate: list[tuple[Pin, Source, User]] = [
        (pin_row, source_row, persona) for pin_row, source_row, persona in page_rows
    ]

    next_marker: str | None = None
    if len(rows) > slice_size:
        pivot_pin, _pivot_source, _pivot_actor = rows[slice_size]
        next_marker = encode_feed_cursor(pivot_pin.created_at, pivot_pin.id)

    return hydrate, next_marker


async def last_comments_overview(session: AsyncSession, pin_pk: int) -> list[dict]:
    chatter = await fetch_comment_thread(session, pin_pk)
    tail = chatter[-2:]
    identifiers = sorted({segment.user_id for segment in tail})
    if not identifiers:
        return []

    from filigrane_api.services.social_notifications import fetch_handles

    labels = await fetch_handles(session, identifiers)
    synopsis: list[dict] = []
    for segment in tail:
        synopsis.append(
            {
                "id": segment.id,
                "handle": labels.get(segment.user_id, ""),
                "body": segment.body,
                "created_at": segment.created_at.isoformat(),
            },
        )
    return synopsis

