from __future__ import annotations

from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.models.auth_tokens import MagicLink
from filigrane_api.models.entities import User
from filigrane_api.models.magic_allowlist import MagicLoginAllowlist
from filigrane_api.services.email_identity import normalize_email
from filigrane_api.utils.time import utcnow


async def grant_email(
    session: AsyncSession,
    *,
    raw_email: str,
) -> Literal["ok", "noop", "invalid_email", "user_not_found"]:
    mailbox = normalize_email(raw_email)
    if mailbox is None:
        return "invalid_email"

    user_ok = await session.scalar(select(User.id).where(User.email == mailbox))
    if user_ok is None:
        return "user_not_found"

    existing = await session.scalar(
        select(MagicLoginAllowlist.email).where(MagicLoginAllowlist.email == mailbox),
    )
    if existing is not None:
        return "noop"

    session.add(MagicLoginAllowlist(email=mailbox, granted_at=utcnow()))
    return "ok"


async def revoke_email(
    session: AsyncSession,
    *,
    raw_email: str,
) -> Literal["ok", "invalid_email", "not_on_allowlist"]:
    mailbox = normalize_email(raw_email)
    if mailbox is None:
        return "invalid_email"

    deleted = await session.execute(
        delete(MagicLoginAllowlist).where(MagicLoginAllowlist.email == mailbox),
    )
    if deleted.rowcount == 0:
        return "not_on_allowlist"

    await session.execute(
        delete(MagicLink).where(
            MagicLink.email == mailbox,
            MagicLink.consumed_at.is_(None),
        ),
    )
    return "ok"


async def is_allowed(session: AsyncSession, *, mailbox: str) -> bool:
    row = await session.scalar(
        select(MagicLoginAllowlist.email).where(MagicLoginAllowlist.email == mailbox),
    )
    return row is not None
