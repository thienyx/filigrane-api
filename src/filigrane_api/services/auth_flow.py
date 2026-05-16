from __future__ import annotations

import re
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from filigrane_api.core.config import FiligraneSettings
from filigrane_api.core.logging_config import get_logger
from filigrane_api.core.security import hash_secret, mint_opaque_token
from filigrane_api.models.auth_tokens import MagicLink, SessionToken
from filigrane_api.models.entities import User
from filigrane_api.models.magic_allowlist import MagicLoginAllowlist
from filigrane_api.services import magic_allowlist_ops as allowlist_svc
from filigrane_api.services.email_dispatch import EmailSender
from filigrane_api.services.email_identity import normalize_email
from filigrane_api.utils.time import utcnow

_HANDLE_SAFE = re.compile(r"[^a-z0-9_]+")
_log = get_logger(component="auth_flow")


class AuthFlowError(RuntimeError):
    pass


class InvalidMagicTokenError(AuthFlowError):
    def __init__(self, *, code: str, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class MagicRequestRejectedError(AuthFlowError):
    def __init__(self, *, code: str, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class MagicEmailDeliveryError(AuthFlowError):
    def __init__(self, public_message: str) -> None:
        self.public_message = public_message
        super().__init__(public_message)


_MSG_INVALID_EMAIL = (
    "This email address could not be validated. Check typos and try again."
)
_MSG_USER_MISSING = (
    "No Filigrane account is registered with this email. "
    "Ask a teammate to invite you or create your user first."
)
_MSG_NOT_ALLOWLISTED = (
    "Magic-link sign-in is not enabled for this email yet. "
    "Ask an administrator to add it to the magic login allowlist."
)
_MSG_MAGIC_LINK_BAD = (
    "This sign-in link is invalid, expired, or was already used. "
    "Request a new one from the login page."
)
_MSG_MAGIC_USER_GONE = (
    "This link refers to an account that no longer exists. "
    "Contact your team administrator."
)
_MSG_MAGIC_REVOKED = (
    "Magic-link access was revoked for this email. "
    "Ask an administrator to allowlist it again, then request a new link."
)


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
        _log.warning("magic_rejected", reason="invalid_email", email=inbound_email)
        raise MagicRequestRejectedError(
            code="invalid_email",
            public_message=_MSG_INVALID_EMAIL,
        )

    profile = await session.scalar(select(User).where(User.email == mailbox))
    if profile is None:
        if configuration.auto_provision_users:
            profile = await _provision_member(session, mailbox=mailbox)
            _log.info("magic_user_provisioned", email=mailbox, handle=profile.handle)
        else:
            _log.warning("magic_rejected", reason="user_missing", email=mailbox)
            raise MagicRequestRejectedError(
                code="user_not_found",
                public_message=_MSG_USER_MISSING,
            )

    if not await allowlist_svc.is_allowed(session, mailbox=mailbox):
        if configuration.auto_provision_users:
            session.add(MagicLoginAllowlist(email=mailbox, granted_at=utcnow()))
            await session.flush()
            _log.info("magic_allowlisted", email=mailbox)
        else:
            _log.warning("magic_rejected", reason="not_allowlisted", email=mailbox)
            raise MagicRequestRejectedError(
                code="not_allowlisted",
                public_message=_MSG_NOT_ALLOWLISTED,
            )

    await session.execute(
        delete(MagicLink).where(
            MagicLink.email == mailbox,
            MagicLink.consumed_at.is_(None),
        ),
    )

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
    try:
        await sender.send_magic_link(
            to_email=mailbox,
            link=redirect,
            ttl_minutes=configuration.magic_link_ttl_minutes,
        )
    except httpx.HTTPStatusError as exc:
        _log.error(
            "magic_email_failed",
            email=mailbox,
            status=exc.response.status_code,
            body=exc.response.text[:500],
        )
        raise MagicEmailDeliveryError(
            "The email provider rejected the message. "
            "Check FILIGRANE_RESEND_API_KEY and FILIGRANE_EMAIL_FROM "
            "(sender must use a verified domain in Resend).",
        ) from exc
    except Exception as exc:
        _log.error("magic_email_failed", email=mailbox, error=str(exc))
        raise MagicEmailDeliveryError(
            "The sign-in email could not be sent. Try again in a few minutes.",
        ) from exc


async def _provision_member(session: AsyncSession, *, mailbox: str) -> User:
    base_handle = _HANDLE_SAFE.sub("_", mailbox.split("@", 1)[0].lower()).strip("_")
    if not base_handle:
        base_handle = "member"
    base_handle = base_handle[:48]
    candidate = base_handle
    suffix = 1
    while await session.scalar(select(User.id).where(User.handle == candidate)):
        suffix += 1
        candidate = f"{base_handle}_{suffix}"

    member = User(handle=candidate, email=mailbox, name=base_handle.replace("_", " "))
    session.add(member)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(User).where(User.email == mailbox))
        if existing is None:
            raise
        return existing
    return member


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
        raise InvalidMagicTokenError(
            code="magic_link_invalid",
            public_message=_MSG_MAGIC_LINK_BAD,
        )

    holder = await session.scalar(select(User).where(User.email == invitation.email))
    if holder is None:
        raise InvalidMagicTokenError(
            code="user_missing",
            public_message=_MSG_MAGIC_USER_GONE,
        )

    if not await allowlist_svc.is_allowed(session, mailbox=invitation.email):
        raise InvalidMagicTokenError(
            code="magic_login_revoked",
            public_message=_MSG_MAGIC_REVOKED,
        )

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
