"""ziv.relay.ws — the device socket.

The first frame must be ``hello`` with the device key (never a query string)
within the hello timeout, or the socket closes with 4401. After the ack, a
reader task applies up-frames through the relay and a writer task drains the
device's bounded queue with a per-send timeout, so a slow device never holds
the relay. Either task ending ends the connection, and the relay learns the
device is gone.
"""
from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ziv.wire import Hello, ProtocolError, Reason, up_frame_adapter

from .devices import DeviceConn
from .service import Relay

CLOSE_UNAUTHORIZED = 4401
CLOSE_BAD_FRAME = 4400
CLOSE_TOO_SLOW = 1013


async def _close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:
        pass


async def _refuse(ws: WebSocket, reason: Reason, detail: str, code: int) -> None:
    try:
        await ws.send_text(ProtocolError(reason=reason, detail=detail).model_dump_json())
    except Exception:
        pass
    await _close(ws, code)


async def endpoint(ws: WebSocket) -> None:
    relay: Relay = ws.app.state.relay
    settings = relay.settings
    await ws.accept()
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=settings.hello_timeout_s)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError, KeyError):
        relay.event("ws_refused", reason=Reason.unauthorized, detail="no hello")
        await _close(ws, CLOSE_UNAUTHORIZED)
        return
    try:
        frame = up_frame_adapter.validate_json(raw)
    except ValidationError:
        relay.event("ws_refused", reason=Reason.bad_request, detail="invalid first frame")
        await _refuse(ws, Reason.unauthorized, "the first frame must be hello", CLOSE_UNAUTHORIZED)
        return
    if not isinstance(frame, Hello):
        relay.event("ws_refused", reason=Reason.unauthorized, detail=f"first frame {frame.type}")
        await _refuse(ws, Reason.unauthorized, "the first frame must be hello", CLOSE_UNAUTHORIZED)
        return
    device = relay.store.devices.find_by_key(frame.device_key)
    if device is None:
        relay.event("ws_refused", reason=Reason.unauthorized, detail="unknown device key")
        await _refuse(ws, Reason.unauthorized, "unknown device key", CLOSE_UNAUTHORIZED)
        return
    if device.profile != frame.profile:
        relay.event("ws_refused", reason=Reason.spec_mismatch, wearer=device.wearer, detail="profile differs from enrollment")
        await _refuse(ws, Reason.spec_mismatch, "profile differs from enrollment", CLOSE_BAD_FRAME)
        return

    conn = DeviceConn(device, profile=frame.profile, pace_ms=frame.pace_ms)
    ack = relay.device_hello(conn, frame)
    try:
        await asyncio.wait_for(ws.send_text(ack.model_dump_json(by_alias=True, exclude_none=True)),
                               timeout=settings.send_timeout_s)
    except Exception:
        relay.device_gone(conn)
        await _close(ws, CLOSE_TOO_SLOW)
        return

    reader = asyncio.create_task(_read_loop(ws, relay, conn))
    writer = asyncio.create_task(_write_loop(ws, conn, settings.send_timeout_s))
    try:
        await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # The synchronous bookkeeping comes first: if the server is tearing this
        # handler down, no await below may pre-empt the relay learning the
        # device is gone. ``asyncio.wait`` (not ``gather``) so a cancellation of
        # this handler keeps its own identity through the cleanup.
        relay.device_gone(conn)
        conn.close()
        for task in (reader, writer):
            if not task.done():
                task.cancel()
        await asyncio.wait({reader, writer})
        await _close(ws, CLOSE_TOO_SLOW if conn.overflow else 1000)


async def _read_loop(ws: WebSocket, relay: Relay, conn: DeviceConn) -> None:
    while not conn.closed:
        try:
            raw = await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError, KeyError):
            return
        try:
            frame = up_frame_adapter.validate_json(raw)
        except ValidationError:
            relay.event("ws_bad_frame", wearer=conn.wearer, reason=Reason.bad_request)
            conn.offer(ProtocolError(reason=Reason.bad_request, detail="frame failed validation"))
            continue
        try:
            reply = relay.device_frame(conn, frame)
        except Exception as exc:  # a bug must surface as an event, not a dead socket loop
            relay.event("ws_frame_error", wearer=conn.wearer, detail=type(exc).__name__)
            reply = ProtocolError(reason=Reason.bad_request, detail="frame not applied")
        if reply is not None:
            conn.offer(reply)


async def _write_loop(ws: WebSocket, conn: DeviceConn, send_timeout_s: float) -> None:
    while True:
        text = await conn.queue.get()
        if text is None:
            return
        try:
            await asyncio.wait_for(ws.send_text(text), timeout=send_timeout_s)
        except Exception:
            return
        conn.sent_frames += 1
        if conn.overflow:
            return
