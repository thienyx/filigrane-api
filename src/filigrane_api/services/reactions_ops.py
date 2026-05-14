from __future__ import annotations

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.core.notify_hub import NotifyHub
from filigrane_api.models.entities import Comment, Pin, Reaction
from filigrane_api.models.enums import NotificationKind, ReactionTarget
from filigrane_api.services.social_notifications import fetch_handles, notify_users
from filigrane_api.services.source_ops import bump_source_revision
from filigrane_api.utils.time import utcnow


async def toggle_reaction(
    session: AsyncSession,
    *,
    viewer_id: int,
    reaction_target: ReactionTarget,
    target_pk: int,
    reaction_kind: str,
    hub: NotifyHub | None,
) -> bool:
    trimmed = reaction_kind.strip()
    if not trimmed:
        msg = "Kind required"
        raise ValueError(msg)

    await _assert_reaction_target(session, reaction_target, target_pk)

    locator: Select[tuple[Reaction]] = select(Reaction).where(
        Reaction.target == reaction_target,
        Reaction.target_id == target_pk,
        Reaction.user_id == viewer_id,
        Reaction.kind == trimmed,
    )
    duplicate = await session.scalar(locator)
    source_anchor = await _resolve_source_anchor(session, reaction_target, target_pk)
    beneficiary = await _identify_subject_owner(session, reaction_target, target_pk)

    if duplicate is not None:
        await session.execute(
            delete(Reaction).where(
                Reaction.target == reaction_target,
                Reaction.target_id == target_pk,
                Reaction.user_id == viewer_id,
                Reaction.kind == trimmed,
            )
        )
        if source_anchor is not None:
            await bump_source_revision(session, source_anchor)
        await session.flush()
        return False

    reaction_row = Reaction(
        target=reaction_target,
        target_id=target_pk,
        user_id=viewer_id,
        kind=trimmed,
        created_at=utcnow(),
    )
    session.add(reaction_row)
    if source_anchor is not None:
        await bump_source_revision(session, source_anchor)
    await session.flush()

    if beneficiary is not None and beneficiary != viewer_id:
        alias_map = await fetch_handles(session, [viewer_id])
        payload = {
            "target": reaction_target.value,
            "target_id": target_pk,
            "kind": trimmed,
            "actor_handle": alias_map.get(viewer_id, str(viewer_id)),
        }
        if source_anchor:
            payload["source_id"] = source_anchor

        await notify_users(
            session,
            recipients=[beneficiary],
            kind=NotificationKind.REACTION_ADDED,
            payload=payload,
            hub=hub,
        )

    await session.refresh(reaction_row)
    return True


async def _assert_reaction_target(
    session: AsyncSession,
    reaction_target: ReactionTarget,
    target_pk: int,
) -> None:
    if reaction_target == ReactionTarget.PIN:
        pin_row = await session.get(Pin, target_pk)
        if pin_row is None:
            raise LookupError("pin_missing")
        return
    comment_row = await session.get(Comment, target_pk)
    if comment_row is None or comment_row.deleted_at is not None:
        raise LookupError("comment_missing")


async def _resolve_source_anchor(
    session: AsyncSession,
    reaction_target: ReactionTarget,
    target_pk: int,
) -> int | None:
    if reaction_target == ReactionTarget.PIN:
        stmt = select(Pin.source_id).where(Pin.id == target_pk)
        result = await session.scalar(stmt)
        return int(result) if result is not None else None
    stmt = (
        select(Pin.source_id)
        .join(Comment, Comment.pin_id == Pin.id)
        .where(
            Comment.id == target_pk,
            Comment.deleted_at.is_(None),
        )
        .limit(1)
    )
    fetched = await session.scalar(stmt)
    return int(fetched) if fetched is not None else None


async def _identify_subject_owner(
    session: AsyncSession,
    reaction_target: ReactionTarget,
    target_pk: int,
) -> int | None:
    if reaction_target == ReactionTarget.PIN:
        stmt = select(Pin.user_id).where(Pin.id == target_pk)
    else:
        stmt = select(Comment.user_id).where(Comment.id == target_pk)

    fetched = await session.scalar(stmt)
    return int(fetched) if fetched is not None else None
