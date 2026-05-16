from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials

from filigrane_api.deps import (
    SessionWire,
    SettingsWire,
    credential_scheme,
    sniff_session_plaintext,
)
from filigrane_api.schemas.payloads import (
    LoginEnvelope,
    MagicConsume,
    MagicRequest,
    UserPublic,
)
from filigrane_api.services import auth_flow as auth_flow_svc
from filigrane_api.services.email_dispatch import build_email_sender
from filigrane_api.traffic import traffic_guard

router = APIRouter(prefix="/auth", tags=["authentication"])

_MAGIC_REJECT_HTTP = {
    "invalid_email": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "user_not_found": status.HTTP_404_NOT_FOUND,
    "not_allowlisted": status.HTTP_403_FORBIDDEN,
}


@router.post("/magic-link/request", status_code=status.HTTP_202_ACCEPTED)
@traffic_guard.limit("25/hour")
async def solicit_magic_delivery(
    request: Request,
    packet: MagicRequest,
    session_bundle: SessionWire,
    runtime: SettingsWire,
) -> Response:
    courier = build_email_sender(
        api_key=runtime.resend_api_key,
        from_address=runtime.email_from,
    )

    try:
        await auth_flow_svc.start_magic_challenge(
            session_bundle,
            configuration=runtime,
            sender=courier,
            inbound_email=packet.email,
            invite_ip=request.client.host if request.client else None,
            invite_agent=request.headers.get("user-agent"),
        )
    except auth_flow_svc.MagicRequestRejectedError as exc:
        status_code = _MAGIC_REJECT_HTTP.get(
            exc.code,
            status.HTTP_400_BAD_REQUEST,
        )
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.public_message,
            },
        ) from None
    except auth_flow_svc.MagicEmailDeliveryError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "email_delivery_failed",
                "message": exc.public_message,
            },
        ) from None

    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/magic-link/consume", status_code=status.HTTP_200_OK)
async def finish_magic_delivery(
    packet: MagicConsume,
    session_bundle: SessionWire,
    runtime: SettingsWire,
    ingress: Request,
    downstream: Response,
) -> LoginEnvelope:
    try:
        holder, plaintext = await auth_flow_svc.redeem_magic_challenge(
            session_bundle,
            configuration=runtime,
            plaintext_token=packet.token,
            client_agent=ingress.headers.get("user-agent"),
        )
    except auth_flow_svc.InvalidMagicTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": exc.code,
                "message": exc.public_message,
            },
        ) from None

    cookie_key = runtime.session_cookie_name()

    downstream.set_cookie(
        key=cookie_key,
        value=plaintext,
        httponly=True,
        secure=runtime.session_cookie_secure,
        samesite="none" if runtime.session_cookie_secure else "lax",
        max_age=runtime.session_ttl_days * 86400,
        path="/",
    )

    return LoginEnvelope(
        session_token=plaintext,
        user=UserPublic.model_validate(holder),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def terminate_session_route(
    session_bundle: SessionWire,
    runtime: SettingsWire,
    ingress: Request,
    downstream: Response,
    bearer_fragments: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(credential_scheme),
    ],
) -> Response:
    plaintext = sniff_session_plaintext(ingress, runtime, bearer_fragments)
    if plaintext:
        await auth_flow_svc.revoke_opaque_session(
            session_bundle,
            plaintext_token=plaintext,
        )

    downstream.delete_cookie(
        key=runtime.session_cookie_name(),
        path="/",
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
