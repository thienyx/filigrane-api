from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.models.entities import Follow, User


class SocialGraphConflict(RuntimeError):
    pass


async def subscribe_to_handle(
    session: AsyncSession,
    *,
    follower_id: int,
    target_handle: str,
) -> Follow:
    target = await session.scalar(select(User).where(User.handle == target_handle))
    if target is None:
        raise LookupError("missing_user")
    if target.id == follower_id:
        msg = "Cannot follow yourself"
        raise SocialGraphConflict(msg)

    existing = await session.scalar(
        select(Follow).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == target.id,
        ),
    )
    if existing:
        return existing

    edge = Follow(follower_id=follower_id, followee_id=target.id)
    session.add(edge)
    await session.flush()
    return edge


async def unsubscribe_from_handle(
    session: AsyncSession,
    *,
    follower_id: int,
    target_handle: str,
) -> None:
    target = await session.scalar(select(User).where(User.handle == target_handle))
    if target is None:
        raise LookupError("missing_user")

    await session.execute(
        delete(Follow).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == target.id,
        ),
    )


async def follower_directory(
    session: AsyncSession,
    *,
    owner_id: int,
) -> list[User]:
    stmt = (
        select(User)
        .join(Follow, Follow.followee_id == User.id)
        .where(Follow.follower_id == owner_id)
        .order_by(User.handle.asc())
    )
    scalar_set = await session.scalars(stmt)
    return list(scalar_set)
