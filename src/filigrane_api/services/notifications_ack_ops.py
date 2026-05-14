from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.models.entities import Notification, SourceActivityRead
from filigrane_api.utils.time import utcnow


async def inbox_slice(
    session: AsyncSession,
    *,
    viewer_id: int,
    chunk: int,
    cursor_dt: datetime | None,
    cursor_pk: int | None,
) -> list[Notification]:
    stmt: Select[tuple[Notification]] = select(Notification).where(
        Notification.user_id == viewer_id,
    )
    if cursor_dt is not None and cursor_pk is not None:
        stmt = stmt.where(
            tuple_(Notification.created_at, Notification.id)
            < tuple_(cursor_dt, cursor_pk),
        )

    stmt = stmt.order_by(
        Notification.created_at.desc(),
        Notification.id.desc(),
    ).limit(chunk + 1)
    rows = await session.scalars(stmt)
    return list(rows)


async def mark_selected_read(
    session: AsyncSession,
    *,
    viewer_id: int,
    notification_keys: list[int],
) -> None:
    if not notification_keys:
        return
    stamped = utcnow()
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == viewer_id,
            Notification.id.in_(notification_keys),
            Notification.read_at.is_(None),
        )
        .values(read_at=stamped),
    )


async def mark_everything_read(
    session: AsyncSession,
    *,
    viewer_id: int,
) -> None:
    stamped = utcnow()
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == viewer_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=stamped),
    )


async def acknowledge_surface_activity(
    session: AsyncSession,
    *,
    viewer_id: int,
    surface_id: int,
) -> None:
    stamped = utcnow()
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == viewer_id,
            Notification.read_at.is_(None),
            Notification.payload.contains({"source_id": surface_id}),
        )
        .values(read_at=stamped),
    )

    upsert_stmt = pg_insert(SourceActivityRead).values(
        user_id=viewer_id,
        source_id=surface_id,
        read_at=stamped,
    )
    upsert_stmt = upsert_stmt.on_conflict_do_update(
        index_elements=["user_id", "source_id"],
        set_={"read_at": stamped},
    )
    await session.execute(upsert_stmt)
