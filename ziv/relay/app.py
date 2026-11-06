"""ziv.relay.app — ``create_app``: the only place the relay is assembled."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import ziv
from ziv.core.model import Refusal
from ziv.store import Store
from ziv.wire import Reason

from . import http, ws
from .clock import Clock, SystemClock
from .composer import Composer, EchoComposer, NebiusComposer
from .service import Relay
from .settings import Settings


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Pure ASGI: refuse a declared body over the limit up front, and stop
    reading an undeclared one the moment it passes the limit."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = self.max_bytes + 1
                if declared > self.max_bytes:
                    await _send_json(send, 413, _too_large(self.max_bytes))
                    return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)


def _too_large(limit: int) -> dict:
    return Refusal(Reason.bad_request, f"request body over {limit} bytes", {"max_body_bytes": limit}).as_dict()


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def default_composer(settings: Settings) -> Composer:
    if settings.compose_configured:
        return NebiusComposer(api_key=settings.nebius_api_key, base_url=settings.nebius_base_url, model=settings.text_model)
    return EchoComposer()


def create_app(
    settings: Settings,
    *,
    clock: Clock | None = None,
    store: Store | None = None,
    composer: Composer | None = None,
) -> FastAPI:
    clock = clock or SystemClock()
    store = store or Store(settings.db_path)
    composer = composer or default_composer(settings)
    relay = Relay(settings, store, clock, composer)
    relay.start()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()

        async def loop() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.poll_s)
                    break
                except asyncio.TimeoutError:
                    pass
                try:
                    await relay.tick(clock.now())
                except Exception as exc:  # the loop must outlive any one bad tick
                    relay.event("tick_error", detail=type(exc).__name__)

        # poll_s <= 0 disables the loop: tests drive ``relay.tick`` themselves
        task = asyncio.create_task(loop()) if settings.poll_s > 0 else None
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                task.cancel()
                await asyncio.wait({task})
            await relay.drain()
            relay.close()

    app = FastAPI(title="Ziv relay", version=ziv.__version__, lifespan=lifespan)
    app.state.relay = relay
    app.state.settings = settings
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)

    @app.exception_handler(BodyTooLarge)
    async def _body_too_large(request: Request, exc: BodyTooLarge) -> JSONResponse:
        return JSONResponse(status_code=413, content=_too_large(settings.max_body_bytes))

    @app.exception_handler(http.RefusalError)
    async def _refusal(request: Request, exc: http.RefusalError) -> JSONResponse:
        return http.refusal_response(exc.refusal, exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # never echo the offending input back through a generic handler
        errors = [{"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                  for e in exc.errors()]
        refusal = Refusal(Reason.bad_request, "the request body failed validation", {"errors": errors})
        return JSONResponse(status_code=422, content=refusal.as_dict())

    app.include_router(http.router)
    app.add_api_websocket_route("/ws", ws.endpoint)
    return app
