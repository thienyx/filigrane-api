from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.core.notify_hub import NotifyHub, SseEnvelope
from filigrane_api.models.entities import Follow, Notification, User
from filigrane_api.models.enums import NotificationKind
from filigrane_api.utils.time import utcnow


async def follower_recipients(session: AsyncSession, actor_id: int) -> list[int]:
    stmt = select(Follow.follower_id).where(Follow.followee_id == actor_id)
    followers = await session.scalars(stmt)
    return [int(pk) for pk in followers if pk != actor_id]


async def fetch_handles(session: AsyncSession, ids: Iterable[int]) -> dict[int, str]:
    uniq = sorted({int(pk) for pk in ids})
    if not uniq:
        return {}
    stmt = select(User.id, User.handle).where(User.id.in_(uniq))
    rows = await session.execute(stmt)
    return {int(pk): handle for pk, handle in rows.all()}


async def notify_users(
    session: AsyncSession,
    *,
    recipients: Sequence[int],
    kind: NotificationKind,
    payload: dict,
    hub: NotifyHub | None,
) -> None:
    targets = sorted({int(pk) for pk in recipients})
    stamped = utcnow()
    pending: list[tuple[int, Notification]] = []
    for recipient in targets:
        row = Notification(
            user_id=recipient,
            kind=kind,
            payload=dict(payload),
            created_at=stamped,
        )
        session.add(row)
        pending.append((recipient, row))
    await session.flush()

    if not hub:
        return

    await asyncio.gather(
        *(
            hub.publish(
                recipient_id,
                SseEnvelope(
                    event=f"notifications.{kind.value}",
                    data={
                        **payload,
                        "notification_id": notification.id,
                    },
                    sse_id=str(notification.id),
                ),
            )
            for recipient_id, notification in pending
        ),
    )


def merge_recipients(*groups: Iterable[int]) -> list[int]:
    bucket: set[int] = set()
    for group in groups:
        bucket.update(int(pk) for pk in group)
    return sorted(bucket)
