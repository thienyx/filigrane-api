from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from filigrane_api.deps import SessionWire, verify_console_gate
from filigrane_api.schemas.payloads import MagicAllowlistMutation
from filigrane_api.services import magic_allowlist_ops as allowlist_svc

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(verify_console_gate)],
)


@router.post("/magic-login-allowlist", status_code=status.HTTP_204_NO_CONTENT)
async def grant_magic_login_email(
    packet: MagicAllowlistMutation,
    session_bundle: SessionWire,
) -> Response:
    outcome = await allowlist_svc.grant_email(
        session_bundle,
        raw_email=packet.email,
    )
    if outcome == "invalid_email":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid_email",
        )
    if outcome == "user_not_found":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/magic-login-allowlist", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_magic_login_email(
    session_bundle: SessionWire,
    email: str = Query(..., min_length=3),
) -> Response:
    outcome = await allowlist_svc.revoke_email(
        session_bundle,
        raw_email=email,
    )
    if outcome == "invalid_email":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid_email",
        )
    if outcome == "not_on_allowlist":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="not_on_allowlist",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
