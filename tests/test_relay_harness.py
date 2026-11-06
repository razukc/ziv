"""Shared harness for the relay integration tests (no tests in this module).

Builds its own app in milliseconds: a temp database, a FakeClock, a
FakeComposer and the background loop disabled, so every tick is one the test
asked for. Imported by the other ``test_relay_*`` modules.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

from ziv.core import spec
from ziv.relay.app import create_app
from ziv.relay.clock import FakeClock
from ziv.relay.composer import ComposeLog, FakeComposer
from ziv.wire import Source

ADMIN = "admin-token-for-tests-0001"
START = 1_800_000_000.0


class HangingComposer:
    """A composer whose compose never returns until released — for body timeouts."""

    source = Source.live

    def __init__(self) -> None:
        self.log = ComposeLog(self.source)
        self.started = 0
        self.release = asyncio.Event()

    async def compose(self, intent, budget_ms, *, profile, pace_ms, api_key=None, kind=None):
        self.started += 1
        await self.release.wait()
        return ["late"]

    def health(self):
        return self.log.health()


class Harness:
    def __init__(self, tmp_path, *, composer=None, **overrides: Any) -> None:
        from ziv.relay.settings import Settings

        self.clock = FakeClock(START)
        self.composer = composer if composer is not None else FakeComposer()
        self.settings = Settings(
            db_path=str(tmp_path / "ziv.sqlite"), admin_token=ADMIN, allow_plain_http=True, poll_s=0.0, **overrides
        )
        self.app = create_app(self.settings, clock=self.clock, composer=self.composer)
        self.relay = self.app.state.relay
        self.store = self.relay.store
        self.client = TestClient(self.app)

    # --- http helpers -------------------------------------------------------

    @staticmethod
    def auth(token: str = ADMIN) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def sender(self, label: str = "friend", scopes=("send", "read"), rate_per_min: int = 60) -> str:
        r = self.client.post("/senders", json={"label": label, "scopes": list(scopes), "rate_per_min": rate_per_min},
                             headers=self.auth())
        assert r.status_code == 201, r.text
        return r.json()["token"]

    def enroll(self, name: str = "band", profile: str = "six_actuator") -> tuple[str, str]:
        code = self.client.post("/devices/enroll-code", headers=self.auth()).json()["code"]
        r = self.client.post("/devices/enroll", json={"code": code, "profile": profile, "name": name})
        assert r.status_code == 201, r.text
        return r.json()["device"], r.json()["device_key"]

    def submit(self, text: str | None = None, *, token: str = ADMIN, **body: Any):
        payload: dict[str, Any] = dict(body)
        if text is not None:
            payload["text"] = text
        return self.client.post("/utterances", json=payload, headers=self.auth(token))

    def get(self, id: str, token: str = ADMIN) -> dict:
        r = self.client.get(f"/utterances/{id}", headers=self.auth(token))
        assert r.status_code == 200, r.text
        return r.json()

    # --- loop helpers -------------------------------------------------------

    def tick(self, now: float | None = None) -> None:
        self.client.portal.call(self.relay.tick, self.clock.now() if now is None else now)

    def drain(self) -> None:
        self.client.portal.call(self.relay.drain)

    def advance(self, seconds: float) -> float:
        return self.clock.advance(seconds)

    # --- device helpers -----------------------------------------------------

    @contextmanager
    def device(self, key: str, *, profile: str = "six_actuator", held=(), last_acked: str | None = None,
               spec_version: int | None = None, pace_ms: int | None = None):
        with self.client.websocket_connect("/ws") as ws:
            hello: dict[str, Any] = {
                "type": "hello", "v": 1, "device_key": key, "profile": profile,
                "spec_version": spec.spec_version() if spec_version is None else spec_version, "held": list(held),
            }
            if last_acked:
                hello["last_acked"] = last_acked
            if pace_ms:
                hello["pace_ms"] = pace_ms
            ws.send_json(hello)
            ack = ws.receive_json()
            yield ws, ack

    @staticmethod
    def sync(ws) -> None:
        """Frames are applied in order: a pong proves everything before it landed."""
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

    @staticmethod
    def frames_until(ws, type_: str, limit: int = 8) -> dict:
        """Receive until a frame of ``type_`` arrives (skipping others), bounded."""
        for _ in range(limit):
            f = ws.receive_json()
            if f["type"] == type_:
                return f
        raise AssertionError(f"no {type_} frame within {limit} frames")

    def events(self, kind: str | None = None, n: int = 500) -> list[dict]:
        return self.store.events.tail(n, kind=kind)

    def db_dump(self) -> str:
        return "\n".join(self.store.conn.iterdump())


@contextmanager
def running(tmp_path, **kw):
    h = Harness(tmp_path, **kw)
    with h.client:
        yield h


def body_json(resp) -> dict:
    return json.loads(resp.content)
