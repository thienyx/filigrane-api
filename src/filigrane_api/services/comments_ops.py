from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.core.notify_hub import NotifyHub
from filigrane_api.models.entities import Comment, Pin
from filigrane_api.models.enums import NotificationKind
from filigrane_api.services.social_notifications import (
    fetch_handles,
    follower_recipients,
    merge_recipients,
    notify_users,
)
from filigrane_api.services.source_ops import bump_source_revision
from filigrane_api.utils.time import utcnow


async def fetch_comment_thread(session: AsyncSession, pin_pk: int) -> list[Comment]:
    stmt: Select[tuple[Comment]] = (
        select(Comment)
        .where(Comment.pin_id == pin_pk, Comment.deleted_at.is_(None))
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    )
    result = await session.scalars(stmt)
    return list(result)


async def post_comment_on_pin(
    session: AsyncSession,
    *,
    actor_id: int,
    pin_pk: int,
    body_text: str,
    parent_pk: int | None,
    hub: NotifyHub | None,
) -> Comment:
    clean_body = body_text.strip()
    if not clean_body:
        msg = "Body required"
        raise ValueError(msg)

    anchor = await session.get(Pin, pin_pk)
    if anchor is None:
        raise LookupError("pin_missing")

    parent_comment = (
        await session.get(Comment, parent_pk) if parent_pk is not None else None
    )
    if parent_pk is not None and parent_comment is None:
        raise LookupError("parent_missing")
    if parent_comment is not None:
        if parent_comment.pin_id != pin_pk:
            raise LookupError("parent_wrong_thread")
        if parent_comment.deleted_at is not None:
            raise LookupError("parent_missing")

    record = Comment(
        pin_id=pin_pk,
        user_id=actor_id,
        parent_id=parent_pk,
        body=clean_body,
        created_at=utcnow(),
    )
    session.add(record)

    await bump_source_revision(session, anchor.source_id)
    await session.flush()

    direct_notify: list[int] = []
    if anchor.user_id != actor_id:
        direct_notify.append(int(anchor.user_id))
    if parent_comment is not None and parent_comment.user_id != actor_id:
        direct_notify.append(int(parent_comment.user_id))

    followers_bundle = await follower_recipients(session, actor_id)
    recipients = merge_recipients(direct_notify, followers_bundle)
    trimmed = sorted({recipient for recipient in recipients if recipient != actor_id})

    aliases = await fetch_handles(session, [actor_id])
    actor_alias = aliases.get(actor_id, str(actor_id))

    payload = {
        "source_id": anchor.source_id,
        "pin_id": pin_pk,
        "comment_id": record.id,
        "actor_handle": actor_alias,
    }
    await notify_users(
        session,
        recipients=trimmed,
        kind=NotificationKind.COMMENT_CREATED,
        payload=payload,
        hub=hub,
    )

    await session.refresh(record)
    return record


async def soft_remove_comment(
    session: AsyncSession,
    *,
    actor_id: int,
    comment_pk: int,
) -> None:
    row = await session.get(Comment, comment_pk)
    if row is None or row.user_id != actor_id:
        raise LookupError("comment_missing")
    if row.deleted_at is not None:
        return

    pin_row = await session.get(Pin, row.pin_id)
    row.deleted_at = utcnow()
    if pin_row is not None:
        await bump_source_revision(session, pin_row.source_id)


async def adjust_comment_body(
    session: AsyncSession,
    *,
    actor_id: int,
    comment_pk: int,
    new_body: str,
) -> Comment:
    clean_body = new_body.strip()
    if not clean_body:
        msg = "Body required"
        raise ValueError(msg)

    row = await session.get(Comment, comment_pk)
    if row is None or row.user_id != actor_id or row.deleted_at is not None:
        raise LookupError("comment_missing")

    row.body = clean_body
    row.edited_at = utcnow()
    pin_anchor = await session.get(Pin, row.pin_id)
    if pin_anchor is not None:
        await bump_source_revision(session, pin_anchor.source_id)
    await session.flush()
    await session.refresh(row)
    return row
