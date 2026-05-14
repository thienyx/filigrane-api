from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.models.entities import Comment, Notification, Pin, Reaction
from filigrane_api.models.enums import ReactionTarget


async def unread_exists(
    session: AsyncSession,
    *,
    user_id: int,
    source_id: int,
) -> bool:
    stmt = (
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.payload.contains({"source_id": source_id}),
        )
        .limit(1)
    )
    return await session.scalar(stmt) is not None


async def count_live_comments(session: AsyncSession, source_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(Comment)
        .join(Pin, Comment.pin_id == Pin.id)
        .where(Pin.source_id == source_id, Comment.deleted_at.is_(None))
    )
    return int(await session.scalar(stmt))


async def reaction_totals(session: AsyncSession, source_id: int) -> dict[str, int]:
    pin_ids = select(Pin.id).where(Pin.source_id == source_id)
    stmt = (
        select(Reaction.kind, func.count())
        .where(
            Reaction.target == ReactionTarget.PIN,
            Reaction.target_id.in_(pin_ids),
        )
        .group_by(Reaction.kind)
    )
    rows = await session.execute(stmt)
    buckets: dict[str, int] = {}
    for kind, total in rows:
        buckets[str(kind)] = int(total)
    return buckets
