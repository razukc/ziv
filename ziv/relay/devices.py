"""ziv.relay.devices — the in-process registry of connected devices.

One ``DeviceConn`` per open socket, with a bounded outbound queue. A full
queue or a slow send ends the connection; it never blocks the relay.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable

from pydantic import BaseModel

from ziv.core.model import Device
from ziv.wire import Profile, down_frame_adapter

DEFAULT_QUEUE = 32


class DeviceConn:
    def __init__(self, device: Device, *, profile: Profile, pace_ms: int | None, maxsize: int = DEFAULT_QUEUE) -> None:
        self.device = device
        self.id = device.id
        self.wearer = device.wearer
        self.profile = profile
        self.pace_ms = pace_ms
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=maxsize)
        self.closed = False
        self.overflow = False
        self.sent_frames = 0

    def offer(self, frame: BaseModel) -> bool:
        """Queue one validated down-frame. False when the device is too slow."""
        if self.closed:
            return False
        text = down_frame_adapter.dump_json(frame, by_alias=True, exclude_none=True).decode("utf-8")
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            self.overflow = True
            return False
        return True

    def close(self) -> None:
        self.closed = True
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            self.overflow = True


class DeviceRegistry:
    def __init__(self) -> None:
        self._conns: dict[str, DeviceConn] = {}

    def connect(self, conn: DeviceConn) -> DeviceConn | None:
        """Register; a previous socket for the same device is closed and returned."""
        old = self._conns.get(conn.id)
        self._conns[conn.id] = conn
        if old is not None and old is not conn:
            old.close()
            return old
        return None

    def disconnect(self, conn: DeviceConn) -> bool:
        """True when ``conn`` was the live socket for its device (so the device is now gone)."""
        if self._conns.get(conn.id) is conn:
            del self._conns[conn.id]
            return True
        return False

    def get(self, device_id: str) -> DeviceConn | None:
        return self._conns.get(device_id)

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._conns

    def count(self) -> int:
        return len(self._conns)

    def ids(self) -> list[str]:
        return list(self._conns)

    def for_wearer(self, wearer: str) -> list[DeviceConn]:
        return [c for c in self._conns.values() if c.wearer == wearer]

    def send(self, device_id: str, frame: BaseModel) -> bool:
        conn = self._conns.get(device_id)
        return conn.offer(frame) if conn is not None else False

    def broadcast(self, wearer: str, frame: BaseModel, *, exclude: Iterable[str] = ()) -> int:
        skip = set(exclude)
        return sum(1 for c in self.for_wearer(wearer) if c.id not in skip and c.offer(frame))
