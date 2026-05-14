from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness_pulse() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_pulse(request: Request) -> dict[str, str]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return {"status": "degraded"}

    async with factory() as session_bundle:
        await session_bundle.execute(text("SELECT 1"))
    return {"status": "ready"}
