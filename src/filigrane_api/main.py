from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from filigrane_api.core.config import FiligraneSettings, get_settings
from filigrane_api.core.db import create_engine, create_sessionmaker
from filigrane_api.core.logging_config import configure_logging
from filigrane_api.core.notify_hub import NotifyHub
from filigrane_api.deps import verify_console_gate
from filigrane_api.middleware.request_id import RequestIdMiddleware
from filigrane_api.routes import auth, health, internal_access, workspace
from filigrane_api.traffic import traffic_guard


@asynccontextmanager
async def runtime_lifecycle(app_scope: FastAPI) -> AsyncIterator[None]:
    runtime_snapshot = get_settings()
    configure_logging(runtime_snapshot.log_level)

    database_pointer = runtime_snapshot.database_url
    if database_pointer:
        async_engine_stack = create_engine(database_pointer)
        session_stack = create_sessionmaker(async_engine_stack)
        app_scope.state.engine = async_engine_stack
        app_scope.state.session_factory = session_stack
    else:
        app_scope.state.engine = None
        app_scope.state.session_factory = None

    app_scope.state.settings = runtime_snapshot
    app_scope.state.notify_hub = NotifyHub()
    app_scope.state.limiter = traffic_guard

    structlog.get_logger(__name__).info(
        "filigrane_startup",
        env=runtime_snapshot.env,
        database=bool(database_pointer),
        openapi=runtime_snapshot.openapi_enabled,
    )

    yield

    scoped_engine = getattr(app_scope.state, "engine", None)
    if scoped_engine is not None:
        await scoped_engine.dispose()


def _merge_browser_origins(snapshot: FiligraneSettings) -> list[str]:
    merged = [*snapshot.parsed_cors_origins(), *snapshot.chrome_extension_origins()]
    if merged:
        return merged
    if snapshot.env == "development":
        return ["http://127.0.0.1:3000", "http://localhost:3000"]
    return []


def build_application() -> FastAPI:
    snapshot = get_settings()
    expose_contracts = snapshot.openapi_enabled

    api_gateway = FastAPI(
        title="Filigrane",
        lifespan=runtime_lifecycle,
        openapi_url="/openapi.json" if expose_contracts else None,
        docs_url="/docs" if expose_contracts else None,
        redoc_url=None,
        version="0.1.0",
    )

    api_gateway.state.limiter = traffic_guard

    api_gateway.add_middleware(RequestIdMiddleware)

    api_gateway.add_middleware(SlowAPIMiddleware)
    api_gateway.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    allow_targets = _merge_browser_origins(snapshot)
    api_gateway.add_middleware(
        CORSMiddleware,
        allow_origins=allow_targets or ["http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_gateway.include_router(health.router)
    api_gateway.include_router(auth.router, prefix="/v1")
    api_gateway.include_router(workspace.router, prefix="/v1")
    api_gateway.include_router(internal_access.router)

    @api_gateway.get(
        "/internal/schema",
        include_in_schema=False,
        dependencies=[Depends(verify_console_gate)],
    )
    async def secure_public_contract() -> dict:
        return api_gateway.openapi()

    return api_gateway


app = build_application()


def serve_port_hint() -> int:
    inbound = os.environ.get("PORT")
    if inbound is None:
        return 8000
    return int(inbound)
