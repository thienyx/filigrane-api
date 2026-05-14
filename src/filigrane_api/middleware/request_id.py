"""HTTP middleware exposing request correlation ids."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-ID"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        inbound = request.headers.get(self.HEADER)
        correlation = inbound if inbound else uuid.uuid4().hex
        request.state.request_id = correlation
        response = await call_next(request)
        response.headers[self.HEADER] = correlation
        return response
