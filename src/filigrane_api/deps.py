from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from filigrane_api.core.config import FiligraneSettings, get_settings
from filigrane_api.core.notify_hub import NotifyHub
from filigrane_api.core.principal import Principal
from filigrane_api.services import auth_flow as auth_flow_svc

credential_scheme = HTTPBearer(auto_error=False)

SettingsWire = Annotated[FiligraneSettings, Depends(get_settings)]


async def acquire_database_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state,
        "session_factory",
        None,
    )
    if factory is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database_unconfigured",
        )
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionWire = Annotated[AsyncSession, Depends(acquire_database_session)]


def peek_session_cookie(
    raw_request: Request,
    runtime: FiligraneSettings,
) -> str | None:
    moniker = runtime.session_cookie_name()
    return raw_request.cookies.get(moniker)


def sniff_session_plaintext(
    request: Request,
    runtime: FiligraneSettings,
    bearer_packet: HTTPAuthorizationCredentials | None,
) -> str | None:
    header_piece = bearer_packet.credentials if bearer_packet else None
    cookie_piece = peek_session_cookie(request, runtime)
    return header_piece or cookie_piece


async def require_identity(
    request: Request,
    session_bundle: SessionWire,
    runtime: SettingsWire,
    bearer_packet: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(credential_scheme),
    ],
) -> Principal:
    plaintext = sniff_session_plaintext(request, runtime, bearer_packet)
    if plaintext is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
        )

    hydrated = await auth_flow_svc.lookup_active_session(
        session_bundle,
        plaintext_token=plaintext,
    )
    if hydrated is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="session_invalid",
        )

    _ledger, profile = hydrated

    return Principal(user_id=int(profile.id))


PersonaWire = Annotated[Principal, Depends(require_identity)]


async def realtime_bus(request: Request) -> NotifyHub:
    return request.app.state.notify_hub


RealtimeWire = Annotated[NotifyHub, Depends(realtime_bus)]


def asynchronous_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


FactoryWire = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(asynchronous_factory),
]


def verify_console_gate(
    request: Request,
    runtime: SettingsWire,
    bearer_packet: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(credential_scheme),
    ],
) -> None:
    if runtime.admin_token is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="admin_disabled",
        )
    provided = bearer_packet.credentials if bearer_packet else None
    forwarded = provided or request.headers.get("x-admin-token")
    if forwarded != runtime.admin_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="admin_only")
