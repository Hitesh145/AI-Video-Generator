"""Refuse oversized uploads before the framework reads them.

FastAPI parses a whole multipart body (spooling large ones to disk) before the endpoint
runs, so a size check inside the endpoint cannot stop a huge upload early. This ASGI
middleware looks at the declared Content-Length and also counts the bytes actually
received, so a body sent in chunks without a length is cut off too.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

MULTIPART_OVERHEAD_BYTES = 64 * 1024     # boundaries and headers around the file itself


class _TooLarge(Exception):
    pass


class UploadSizeLimitMiddleware:
    def __init__(self, app, max_body_bytes: int, message: str, path: str = "/papers") -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.message = message
        self.path = path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return

        declared = next((value for name, value in scope["headers"] if name == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > self.max_body_bytes:
            await self._refuse(scope, receive, send)
            return

        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _TooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._refuse(scope, receive, send)

    async def _refuse(self, scope, receive, send):
        await JSONResponse({"detail": self.message}, status_code=413)(scope, receive, send)
