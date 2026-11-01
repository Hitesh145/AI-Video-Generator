"""Reject state-changing browser requests that come from an origin we do not trust.

SameSite=Lax cookies stop cross-*site* POSTs, but another local site (a different port on
localhost) is the same site, so its requests would carry the session cookie. Browsers
always send an Origin header on cross-origin POSTs, so checking it closes that gap.
Requests without an Origin header (curl, scripts, tests) are not browser cross-site
requests and are allowed.
"""

from __future__ import annotations

from typing import Iterable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware:
    """Plain ASGI middleware (not BaseHTTPMiddleware), so streaming responses are untouched."""

    def __init__(self, app, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed = set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            origin = next((value.decode("latin-1") for name, value in scope["headers"] if name == b"origin"), None)
            if origin is not None and origin not in self.allowed:
                response = JSONResponse({"detail": "Untrusted origin"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def add_origin_check(app: FastAPI, allowed_origins: Iterable[str]) -> None:
    app.add_middleware(OriginCheckMiddleware, allowed_origins=list(allowed_origins))
