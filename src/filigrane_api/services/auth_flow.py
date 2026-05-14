from __future__ import annotations

from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.core.config import FiligraneSettings
from filigrane_api.core.security import hash_secret, mint_opaque_token
from filigrane_api.models.auth_tokens import MagicLink, SessionToken
from filigrane_api.models.entities import User
from filigrane_api.services.email_dispatch import EmailSender
from filigrane_api.utils.time import utcnow


class AuthFlowError(RuntimeError):
    pass


class InvalidMagicTokenError(AuthFlowError):
    pass


def normalize_email(candidate: str) -> str | None:
    trimmed = candidate.strip().lower()
    if not trimmed:
        return None
    try:
        parsed = validate_email(trimmed, check_deliverability=False)
        return parsed.email.lower()
    except EmailNotValidError:
        return None


async def start_magic_challenge(
    session: AsyncSession,
    *,
    configuration: FiligraneSettings,
    sender: EmailSender,
    inbound_email: str,
    invite_ip: str | None,
    invite_agent: str | None,
) -> None:
    mailbox = normalize_email(inbound_email)
    if mailbox is None:
        return

    profile = await session.scalar(select(User).where(User.email == mailbox))
    if profile is None:
        return

    secret_fragment = mint_opaque_token(32)
    digest = hash_secret(secret_fragment)
    deadline = utcnow() + timedelta(minutes=configuration.magic_link_ttl_minutes)
    invitation = MagicLink(
        email=mailbox,
        token_hash=digest,
        expires_at=deadline,
        request_ip=invite_ip,
        user_agent=invite_agent,
        created_at=utcnow(),
    )
    session.add(invitation)

    landing = configuration.public_app_url.rstrip("/")
    redirect = f"{landing}/magic?token={secret_fragment}"
    await sender.send_magic_link(to_email=mailbox, link=redirect)


async def redeem_magic_challenge(
    session: AsyncSession,
    *,
    configuration: FiligraneSettings,
    plaintext_token: str,
    client_agent: str | None,
) -> tuple[User, str]:
    hashed = hash_secret(plaintext_token)
    stmt = (
        select(MagicLink)
        .where(
            MagicLink.token_hash == hashed,
            MagicLink.consumed_at.is_(None),
            MagicLink.expires_at > utcnow(),
        )
        .limit(1)
        .with_for_update()
    )
    invitation = await session.scalar(stmt)
    if invitation is None:
        raise InvalidMagicTokenError("invalid_magic_link")

    holder = await session.scalar(select(User).where(User.email == invitation.email))
    if holder is None:
        raise InvalidMagicTokenError("user_missing")

    invitation.consumed_at = utcnow()

    plaintext_session = mint_opaque_token(48)
    session_row = SessionToken(
        user_id=holder.id,
        token_hash=hash_secret(plaintext_session),
        expires_at=utcnow() + timedelta(days=configuration.session_ttl_days),
        last_seen_at=utcnow(),
        user_agent=client_agent,
        created_at=utcnow(),
    )
    session.add(session_row)

    await session.flush()
    return holder, plaintext_session


async def revoke_opaque_session(
    session: AsyncSession,
    *,
    plaintext_token: str,
) -> None:
    digest = hash_secret(plaintext_token)
    await session.execute(delete(SessionToken).where(SessionToken.token_hash == digest))


async def lookup_active_session(
    session: AsyncSession,
    *,
    plaintext_token: str,
) -> tuple[SessionToken, User] | None:
    digest = hash_secret(plaintext_token)
    stmt = (
        select(SessionToken, User)
        .join(User, SessionToken.user_id == User.id)
        .where(
            SessionToken.token_hash == digest,
            SessionToken.expires_at > utcnow(),
        )
        .limit(1)
    )
    bundle = await session.execute(stmt)
    row = bundle.first()
    if row is None:
        return None

    ledger, profile = row[0], row[1]

    ledger.last_seen_at = utcnow()
    await session.flush()
    return ledger, profile


async def hydrate_user_handle(
    session: AsyncSession,
    *,
    handle_slug: str,
) -> User | None:
    return await session.scalar(
        select(User).where(User.handle == handle_slug),
    )
