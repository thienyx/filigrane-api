from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import Select, select, tuple_

from filigrane_api.deps import FactoryWire, PersonaWire, RealtimeWire, SessionWire
from filigrane_api.models.entities import Pin, User
from filigrane_api.schemas.payloads import (
    CommentPatch,
    CommentWrite,
    NotificationsRead,
    PinWrite,
    ReactionWrite,
    ResolvePayload,
    UserPublic,
)
from filigrane_api.services import auth_flow as auth_flow_svc
from filigrane_api.services.comments_ops import (
    adjust_comment_body,
    fetch_comment_thread,
    post_comment_on_pin,
    soft_remove_comment,
)
from filigrane_api.services.feed_ops import (
    collect_feed_pins,
    decode_feed_cursor,
    encode_feed_cursor,
    last_comments_overview,
)
from filigrane_api.services.notifications_ack_ops import (
    acknowledge_surface_activity,
    inbox_slice,
    mark_everything_read,
    mark_selected_read,
)
from filigrane_api.services.pins_ops import create_or_restore_pin, remove_pin_owned
from filigrane_api.services.reactions_ops import toggle_reaction
from filigrane_api.services.resolve_ops import (
    hydrate_extension_surface,
    summarize_feed_digest,
)

router = APIRouter(tags=["filigrane"])


@router.get("/me", response_model=UserPublic)
async def summarize_self(
    persona: PersonaWire,
    session_bundle: SessionWire,
) -> UserPublic:
    snapshot = await session_bundle.get(User, persona.user_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_missing")
    return UserPublic.model_validate(snapshot)


@router.get("/users/{handle}", response_model=UserPublic)
async def inspect_public_profile(
    handle: str,
    session_bundle: SessionWire,
) -> UserPublic:
    persona = await auth_flow_svc.hydrate_user_handle(
        session_bundle,
        handle_slug=handle,
    )
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_missing")
    return UserPublic.model_validate(persona)


@router.post("/users/{handle}/follow", status_code=status.HTTP_201_CREATED)
async def follow_operator(
    handle: str,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> Response:
    from filigrane_api.services.social_graph_ops import (
        SocialGraphConflict,
        subscribe_to_handle,
    )

    try:
        await subscribe_to_handle(
            session_bundle,
            follower_id=persona.user_id,
            target_handle=handle,
        )
    except SocialGraphConflict as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_missing") from None

    return Response(status_code=status.HTTP_201_CREATED)


@router.delete("/users/{handle}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_operator(
    handle: str,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> Response:
    from filigrane_api.services.social_graph_ops import unsubscribe_from_handle

    try:
        await unsubscribe_from_handle(
            session_bundle,
            follower_id=persona.user_id,
            target_handle=handle,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_missing") from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/following", response_model=list[UserPublic])
async def list_my_constellation(
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> list[UserPublic]:
    from filigrane_api.services.social_graph_ops import follower_directory

    roster = await follower_directory(session_bundle, owner_id=persona.user_id)
    return [UserPublic.model_validate(entry) for entry in roster]


@router.post("/sources/resolve")
async def resolve_surface_for_viewer(
    payload: ResolvePayload,
    session_bundle: SessionWire,
    persona: PersonaWire,
    jobs: BackgroundTasks,
    factory: FactoryWire,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    body, tag = await hydrate_extension_surface(
        session_bundle,
        viewer_pk=persona.user_id,
        raw_location=payload.url,
        background_jobs=jobs,
        factory=factory,
    )
    if if_none_match and if_none_match == tag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    return JSONResponse(content=body, headers={"ETag": tag})


@router.post("/sources/{surface_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_surface_digest(
    surface_id: int,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> Response:
    await acknowledge_surface_activity(
        session_bundle,
        viewer_id=persona.user_id,
        surface_id=surface_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pins")
async def anchor_new_pin(
    payload: PinWrite,
    session_bundle: SessionWire,
    persona: PersonaWire,
    jobs: BackgroundTasks,
    hub: RealtimeWire,
    factory: FactoryWire,
) -> Response:
    try:
        record, spawned = await create_or_restore_pin(
            session_bundle,
            user_id=persona.user_id,
            url_value=payload.url,
            source_pk=payload.source_id,
            memo=payload.note,
            hub=hub,
            background=jobs,
            session_factory=factory,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="source_missing",
        ) from None

    status_code = status.HTTP_201_CREATED if spawned else status.HTTP_200_OK

    return JSONResponse(
        status_code=status_code,
        content={
            "id": record.id,
            "source_id": record.source_id,
            "note": record.note,
            "created_at": record.created_at.isoformat(),
        },
    )


@router.delete("/pins/{pin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def drop_pin_by_owner(
    pin_id: int,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> Response:
    try:
        await remove_pin_owned(
            session_bundle,
            user_id=persona.user_id,
            pin_id=pin_id,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="pin_missing") from None
    except PermissionError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="not_owner") from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources/{surface_id}/pins")
async def enumerate_surface_pins(
    surface_id: int,
    session_bundle: SessionWire,
    _persona: PersonaWire,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    cursor_dt = None
    cursor_pk = None
    if cursor:
        bucket = decode_feed_cursor(cursor)
        if bucket is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_cursor")
        cursor_dt = bucket.anchored
        cursor_pk = bucket.pin_identifier

    stmt: Select[tuple[Pin, User]] = (
        select(Pin, User)
        .join(User, Pin.user_id == User.id)
        .where(Pin.source_id == surface_id)
    )
    if cursor_dt is not None and cursor_pk is not None:
        stmt = stmt.where(
            tuple_(Pin.created_at, Pin.id) < tuple_(cursor_dt, cursor_pk),
        )

    stmt = stmt.order_by(Pin.created_at.desc(), Pin.id.desc()).limit(limit + 1)
    rows = await session_bundle.execute(stmt)
    batch = rows.all()
    page = batch[:limit]
    next_cursor = None
    if len(batch) > limit:
        pivot_pin, _ = batch[limit]
        next_cursor = encode_feed_cursor(pivot_pin.created_at, pivot_pin.id)

    serialized = []
    for pin_row, persona_row in page:
        serialized.append(
            {
                "id": pin_row.id,
                "handle": persona_row.handle,
                "note": pin_row.note,
                "created_at": pin_row.created_at.isoformat(),
            },
        )

    return {"items": serialized, "next_cursor": next_cursor}


@router.get("/feed")
async def social_feed_wall(
    session_bundle: SessionWire,
    persona: PersonaWire,
    cursor_token: str | None = Query(default=None, alias="cursor"),
    limit: int = Query(default=20, ge=1, le=100),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    navigator = decode_feed_cursor(cursor_token) if cursor_token else None
    hydrate, onward = await collect_feed_pins(
        session_bundle,
        viewer_pk=persona.user_id,
        slice_size=limit,
        navigator=navigator,
    )

    items = []
    for pin_row, surface_row, curator in hydrate:
        payload = await last_comments_overview(session_bundle, pin_row.id)
        items.append(
            {
                "pin": {
                    "id": pin_row.id,
                    "note": pin_row.note,
                    "created_at": pin_row.created_at.isoformat(),
                    "handle": curator.handle,
                },
                "source": {
                    "id": surface_row.id,
                    "canonical_url": surface_row.canonical_url,
                    "title": surface_row.title,
                    "kind": surface_row.kind.value,
                },
                "last_comments": payload,
            },
        )

    tag = summarize_feed_digest(hydrate)
    if if_none_match and if_none_match == tag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})

    envelope = {"items": items, "next_cursor": onward}
    return JSONResponse(content=envelope, headers={"ETag": tag})


@router.get("/pins/{pin_id}/comments")
async def read_comment_thread(pin_id: int, session_bundle: SessionWire) -> dict:
    records = await fetch_comment_thread(session_bundle, pin_id)
    chatter = []
    identifiers = sorted({segment.user_id for segment in records})
    from filigrane_api.services.social_notifications import fetch_handles

    handles = await fetch_handles(session_bundle, identifiers)
    for segment in records:
        chatter.append(
            {
                "id": segment.id,
                "handle": handles.get(segment.user_id),
                "body": segment.body,
                "created_at": segment.created_at.isoformat(),
                "parent_id": segment.parent_id,
            },
        )
    return {"items": chatter}


@router.post("/pins/{pin_id}/comments")
async def write_comment_under_pin(
    pin_id: int,
    payload: CommentWrite,
    session_bundle: SessionWire,
    persona: PersonaWire,
    hub: RealtimeWire,
) -> dict:
    try:
        row = await post_comment_on_pin(
            session_bundle,
            actor_id=persona.user_id,
            pin_pk=pin_id,
            body_text=payload.body,
            parent_pk=payload.parent_id,
            hub=hub,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {
        "id": row.id,
        "pin_id": row.pin_id,
        "created_at": row.created_at.isoformat(),
    }


@router.patch("/comments/{comment_id}")
async def edit_comment_piece(
    comment_id: int,
    payload: CommentPatch,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> dict:
    try:
        refreshed = await adjust_comment_body(
            session_bundle,
            actor_id=persona.user_id,
            comment_pk=comment_id,
            new_body=payload.body,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="comment_missing",
        ) from None

    return {
        "id": refreshed.id,
        "body": refreshed.body,
        "edited_at": refreshed.edited_at.isoformat() if refreshed.edited_at else None,
    }


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment_piece(
    comment_id: int,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> Response:
    try:
        await soft_remove_comment(
            session_bundle,
            actor_id=persona.user_id,
            comment_pk=comment_id,
        )
    except LookupError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="comment_missing",
        ) from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/reactions")
async def switch_reaction_state(
    payload: ReactionWrite,
    session_bundle: SessionWire,
    persona: PersonaWire,
    hub: RealtimeWire,
) -> dict:
    try:
        applied = await toggle_reaction(
            session_bundle,
            viewer_id=persona.user_id,
            reaction_target=payload.target_type,
            target_pk=payload.target_id,
            reaction_kind=payload.kind,
            hub=hub,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return {"active": applied}


@router.get("/notifications")
async def fetch_notification_feed(
    session_bundle: SessionWire,
    persona: PersonaWire,
    cursor_token: str | None = Query(default=None, alias="cursor"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    navigator = decode_feed_cursor(cursor_token) if cursor_token else None

    backlog = await inbox_slice(
        session_bundle,
        viewer_id=persona.user_id,
        chunk=limit,
        cursor_dt=navigator.anchored if navigator else None,
        cursor_pk=navigator.pin_identifier if navigator else None,
    )

    page = backlog[:limit]
    onward = None
    if len(backlog) > limit:
        pivot = backlog[limit]
        onward = encode_feed_cursor(pivot.created_at, pivot.id)

    snapshots = []
    for row in page:
        snapshots.append(
            {
                "id": row.id,
                "kind": row.kind.value,
                "payload": row.payload,
                "read_at": row.read_at.isoformat() if row.read_at else None,
                "created_at": row.created_at.isoformat(),
            },
        )

    return {"items": snapshots, "next_cursor": onward}


@router.post("/notifications/mark-read")
async def update_notification_reads(
    payload: NotificationsRead,
    session_bundle: SessionWire,
    persona: PersonaWire,
) -> Response:
    if payload.all:
        await mark_everything_read(
            session_bundle,
            viewer_id=persona.user_id,
        )
    elif payload.ids:
        await mark_selected_read(
            session_bundle,
            viewer_id=persona.user_id,
            notification_keys=payload.ids,
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _pack_sse_fragment(
    *,
    event_name: str | None,
    data_blob: dict,
    sequence: str | None,
) -> str:
    fragments: list[str] = []
    if event_name:
        fragments.append(f"event: {event_name}")
    if sequence:
        fragments.append(f"id: {sequence}")
    fragments.append(f"data: {json.dumps(data_blob, separators=(',', ':'))}")
    fragments.append("")
    fragments.append("")
    return "\n".join(fragments)


@router.get("/notifications/stream")
async def live_notification_fanout(
    hub: RealtimeWire,
    persona: PersonaWire,
) -> StreamingResponse:
    async def broadcaster() -> AsyncIterator[str]:
        queue, teardown = hub.subscribe(persona.user_id)
        try:
            while True:
                try:
                    packet = await asyncio.wait_for(queue.get(), timeout=25.0)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue

                envelope = packet
                yield _pack_sse_fragment(
                    event_name=envelope.event,
                    data_blob=envelope.data or {},
                    sequence=envelope.sse_id,
                )
        finally:
            teardown()

    return StreamingResponse(broadcaster(), media_type="text/event-stream")
