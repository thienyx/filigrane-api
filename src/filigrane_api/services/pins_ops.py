from __future__ import annotations

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from filigrane_api.core.notify_hub import NotifyHub
from filigrane_api.models.entities import Pin, Source
from filigrane_api.models.enums import NotificationKind
from filigrane_api.services.social_notifications import (
    fetch_handles,
    follower_recipients,
    notify_users,
)
from filigrane_api.services.source_ops import bump_source_revision, ensure_source
from filigrane_api.services.source_ops import hydrate_source_payload as metadata_job
from filigrane_api.services.url_canonical import finalize_after_redirects
from filigrane_api.utils.time import utcnow


async def canonicalize_browser_url(raw: str) -> str:
    headers = {"User-Agent": "FiligraneBot/1.0"}
    async with httpx.AsyncClient(headers=headers) as client:
        return await finalize_after_redirects(raw, client)


async def create_or_restore_pin(
    session: AsyncSession,
    *,
    user_id: int,
    url_value: str | None,
    source_pk: int | None,
    memo: str | None,
    hub: NotifyHub | None,
    background: BackgroundTasks,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Pin, bool]:
    if (url_value is None) == (source_pk is None):
        msg = "Specify exactly one of url or source_id"
        raise ValueError(msg)

    if url_value is not None:
        finalized = await canonicalize_browser_url(url_value)
        source_record = await ensure_source(session, finalized)
        background.add_task(
            metadata_job,
            session_factory,
            source_id=source_record.id,
            landing_url=finalized,
        )
    elif source_pk is not None:
        lookup = await session.get(Source, source_pk)
        if lookup is None:
            raise LookupError("source_missing")
        source_record = lookup
    else:
        raise AssertionError("unreachable branch")

    existing_stmt: Select[tuple[Pin]] = select(Pin).where(
        Pin.user_id == user_id,
        Pin.source_id == source_record.id,
    )
    existing_pin = await session.scalar(existing_stmt)
    if existing_pin:
        if memo is not None and memo != existing_pin.note:
            existing_pin.note = memo
            await bump_source_revision(session, source_record.id)
        await session.flush()
        await session.refresh(existing_pin)
        return existing_pin, False

    record = Pin(
        user_id=user_id,
        source_id=source_record.id,
        note=memo,
        created_at=utcnow(),
    )
    session.add(record)
    await bump_source_revision(session, source_record.id)
    await session.flush()

    followers_scope = await follower_recipients(session, user_id)
    handles_lookup = await fetch_handles(session, [user_id])
    alias = handles_lookup.get(user_id, str(user_id))
    await notify_users(
        session,
        recipients=followers_scope,
        kind=NotificationKind.PIN_CREATED,
        payload={
            "source_id": source_record.id,
            "pin_id": record.id,
            "actor_handle": alias,
        },
        hub=hub,
    )

    await session.refresh(record)
    return record, True


async def remove_pin_owned(
    session: AsyncSession,
    *,
    user_id: int,
    pin_id: int,
) -> None:
    pin_row = await session.get(Pin, pin_id)
    if pin_row is None:
        raise LookupError("missing")
    if pin_row.user_id != user_id:
        raise PermissionError("not_owner")

    snapshot_source = pin_row.source_id
    await session.delete(pin_row)
    await bump_source_revision(session, snapshot_source)


async def count_pins(session: AsyncSession, source_pk: int) -> int:
    stmt = select(func.count()).select_from(Pin).where(Pin.source_id == source_pk)
    return int(await session.scalar(stmt))
