from __future__ import annotations

import json
from hashlib import sha256

from fastapi import BackgroundTasks
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from filigrane_api.models.entities import Pin, Source, User
from filigrane_api.services.page_analytics import (
    count_live_comments,
    reaction_totals,
    unread_exists,
)
from filigrane_api.services.pins_ops import canonicalize_browser_url
from filigrane_api.services.source_ops import ensure_source
from filigrane_api.services.source_ops import hydrate_source_payload as metadata_job


def fingerprint_surface(signature: dict) -> str:
    canonical = json.dumps(signature, sort_keys=True, separators=(",", ":"))
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f'W/"{digest}"'


async def hydrate_extension_surface(
    session: AsyncSession,
    *,
    viewer_pk: int,
    raw_location: str,
    background_jobs: BackgroundTasks,
    factory: async_sessionmaker[AsyncSession],
) -> tuple[dict, str]:
    normalized = await canonicalize_browser_url(raw_location)
    surface_row = await ensure_source(session, normalized)
    background_jobs.add_task(
        metadata_job,
        factory,
        source_id=surface_row.id,
        landing_url=normalized,
    )

    tally_pins = await session.scalar(
        select(func.count()).select_from(Pin).where(Pin.source_id == surface_row.id),
    )
    chatter_total = await count_live_comments(session, surface_row.id)
    reaction_map = await reaction_totals(session, surface_row.id)
    unread_flag = await unread_exists(
        session,
        user_id=viewer_pk,
        source_id=surface_row.id,
    )

    locator: Select[tuple[Pin]] = select(Pin).where(
        Pin.user_id == viewer_pk,
        Pin.source_id == surface_row.id,
    )
    viewer_pin = await session.scalar(locator)

    latest_stmt = (
        select(User.handle)
        .join(Pin, Pin.user_id == User.id)
        .where(Pin.source_id == surface_row.id)
        .order_by(Pin.created_at.desc(), Pin.id.desc())
        .limit(9)
    )
    ordered_aliases = await session.scalars(latest_stmt)
    recent_handles = []
    for alias in ordered_aliases.all():
        if alias not in recent_handles:
            recent_handles.append(alias)
        if len(recent_handles) >= 3:
            break

    signature_blob = {
        "revision": int(surface_row.revision),
        "pin_total": int(tally_pins or 0),
        "comment_total": int(chatter_total),
        "reactions": reaction_map,
        "unread": bool(unread_flag),
        "surface": int(surface_row.id),
        "pinned_by_viewer": bool(viewer_pin),
    }

    body = {
        "source": {
            "id": surface_row.id,
            "canonical_url": surface_row.canonical_url,
            "host": surface_row.host,
            "kind": surface_row.kind.value,
            "title": surface_row.title,
            "description": surface_row.description,
            "image_url": surface_row.image_url,
            "published_at": surface_row.published_at.isoformat()
            if surface_row.published_at
            else None,
            "revision": surface_row.revision,
        },
        "my_pin": (
            {
                "id": viewer_pin.id,
                "note": viewer_pin.note,
                "created_at": viewer_pin.created_at.isoformat(),
            }
            if viewer_pin
            else None
        ),
        "pin_count": int(tally_pins or 0),
        "recent_pinners": recent_handles,
        "comment_count": int(chatter_total),
        "reactions_summary": reaction_map,
        "has_unread_activity": bool(unread_flag),
    }

    tag = fingerprint_surface(signature_blob)

    return body, tag


def summarize_feed_digest(rows: list[tuple[Pin, Source, User]]) -> str:
    snapshots = [
        {
            "pin_id": pin_row.id,
            "source_id": surface_row.id,
            "revision": surface_row.revision,
            "ts": pin_row.created_at.timestamp(),
            "pinned_by": persona.handle,
            "memo": pin_row.note,
        }
        for pin_row, surface_row, persona in rows
    ]
    canonical = {"items": snapshots}
    return fingerprint_surface(canonical)
