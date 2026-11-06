"""A real relay on a real loopback port, for the integration and browser tests.

Unlike ``test_relay_harness`` (TestClient, FakeClock, no loop), this runs the
relay under uvicorn in a background thread with the ``SystemClock`` and the
poll loop on, so a headless device or a browser can talk to it over TCP. The
admin token, a sender token and an enroll code are minted through the service
layer before the server thread takes the store. Everything here is bounded by
timeouts; nothing sleeps longer than a poll interval at a time.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from ziv.relay.app import create_app
from ziv.relay.clock import SystemClock
from ziv.relay.composer import EchoComposer
from ziv.relay.settings import Settings
from ziv.wire import CreateSender

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIR = REPO_ROOT / "client"
CONSOLE_DIR = REPO_ROOT / "console"
CLIENT_DIST = CLIENT_DIR / "dist"
CONSOLE_DIST = CONSOLE_DIR / "dist"
DEVICE_CLI = CLIENT_DIST / "device-cli.js"
NODE = shutil.which("node")


def wait_until(pred: Callable[[], bool], what: str, timeout: float = 10.0, every: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(every)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def build_front_end(name: str, *, need: tuple[str, ...]) -> str | None:
    """Build ``<name>/dist`` when its node_modules exist; otherwise use what is
    there. Returns a reason to skip, or None when every ``need`` file exists."""
    directory = REPO_ROOT / name
    dist = directory / "dist"
    if NODE is None:
        return "node is not installed"
    if (directory / "node_modules").is_dir():
        script = ["build.mjs"] if name == "client" else ["scripts/build.mjs"]
        r = subprocess.run([NODE, *script], cwd=directory, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return f"{name} build failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    missing = [n for n in need if not (dist / n).is_file()]
    if missing:
        return f"{name}/dist lacks {', '.join(missing)} (run npm ci && npm run build in {name}/)"
    return None


class LiveRelay:
    """``with LiveRelay(tmp_path) as relay:`` — a relay listening on 127.0.0.1."""

    def __init__(self, tmp_path: Path, *, composer=None, serve_front_ends: bool = False, **overrides: Any) -> None:
        base: dict[str, Any] = dict(
            db_path=str(tmp_path / "ziv.sqlite"), host="127.0.0.1", port=0, allow_plain_http=True, poll_s=0.1,
        )
        if serve_front_ends:
            base["client_dist"] = str(CLIENT_DIST) if (CLIENT_DIST / "index.html").is_file() else None
            base["console_dist"] = str(CONSOLE_DIST) if (CONSOLE_DIST / "index.html").is_file() else None
        base.update(overrides)
        self.settings = Settings(**base)
        self.app = create_app(self.settings, clock=SystemClock(), composer=composer or EchoComposer())
        self.relay = self.app.state.relay
        wearer = self.settings.default_wearer
        self.wearer = wearer
        # minted through the service layer, before the server thread owns the store
        self.admin_token: str = self.relay.mint_admin_token() or ""
        assert self.admin_token, "a fresh database mints an admin token"
        self.sender_token: str = self.relay.create_sender(
            wearer, CreateSender(label="integration", scopes=["send", "read"], rate_per_min=600)).token or ""
        self.enroll_code: str = self.relay.enroll_code(wearer).code
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        self.http = f"http://127.0.0.1:{self.port}"
        self.ws = f"ws://127.0.0.1:{self.port}/ws"
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning", access_log=False,
                                lifespan="on")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, kwargs={"sockets": [self._sock]},
                                        name="ziv-live-relay", daemon=True)
        self.client = httpx.Client(base_url=self.http, timeout=10.0)

    def __enter__(self) -> "LiveRelay":
        self._thread.start()
        wait_until(lambda: self._server.started, "the relay to start", timeout=15)
        wait_until(lambda: self._ok("/health"), "GET /health", timeout=10)
        return self

    def __exit__(self, *exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=15)
        self.client.close()
        try:
            self._sock.close()
        except OSError:
            pass

    def _ok(self, path: str) -> bool:
        try:
            return self.client.get(path).status_code == 200
        except httpx.HTTPError:
            return False

    # --- http helpers -------------------------------------------------------

    def auth(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.sender_token}"}

    def post(self, path: str, body: dict | None = None, *, token: str | None = None, headers: dict | None = None) -> httpx.Response:
        return self.client.post(path, json=body, headers={**self.auth(token), **(headers or {})})

    def get(self, path: str, *, token: str | None = None, **params: Any) -> httpx.Response:
        return self.client.get(path, headers=self.auth(token), params=params or None)

    def view(self, id: str) -> dict:
        r = self.get(f"/utterances/{id}")
        assert r.status_code == 200, r.text
        return r.json()

    def new_enroll_code(self) -> str:
        r = self.client.post("/devices/enroll-code", headers=self.auth(self.admin_token))
        assert r.status_code == 201, r.text
        return r.json()["code"]

    def enroll_device(self, profile: str = "single_actuator", name: str = "headless") -> tuple[str, str]:
        """Enroll over HTTP with the minted code (or a fresh one). Returns (device id, key)."""
        code = self.enroll_code or self.new_enroll_code()
        self.enroll_code = ""  # a code is exchanged once
        r = self.client.post("/devices/enroll", json={"code": code, "profile": profile, "name": name})
        assert r.status_code == 201, r.text
        return r.json()["device"], r.json()["device_key"]

    def wait_state(self, id: str, *states: str, timeout: float = 10.0) -> dict:
        last: dict = {}

        def done() -> bool:
            nonlocal last
            last = self.view(id)
            return last["state"] in states

        wait_until(done, f"utterance {id} in {states} (last: {last.get('state')})", timeout=timeout)
        return last


class DeviceCli:
    """``node client/dist/device-cli.js`` as a subprocess, its JSON lines collected."""

    def __init__(self, relay: LiveRelay, *args: str, cli: Path = DEVICE_CLI) -> None:
        assert NODE is not None, "node is required"
        self.cmd = [NODE, str(cli), "--relay", relay.ws, *args]
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.events: list[dict] = []
        self.stderr: list[str] = []
        self._lock = threading.Lock()
        self._out = threading.Thread(target=self._read_stdout, daemon=True)
        self._err = threading.Thread(target=self._read_stderr, daemon=True)
        self._out.start()
        self._err.start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                ev = {"event": "unparsed", "line": line}
            with self._lock:
                self.events.append(ev)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip("\n"))

    def of(self, name: str) -> list[dict]:
        with self._lock:
            return [e for e in self.events if e.get("event") == name]

    def names(self) -> list[str]:
        with self._lock:
            return [str(e.get("event")) for e in self.events]

    def wait_for(self, pred: Callable[[dict], bool], what: str, timeout: float = 15.0) -> dict:
        found: list[dict] = []

        def check() -> bool:
            with self._lock:
                found[:] = [e for e in self.events if pred(e)]
            return bool(found)

        wait_until(check, f"{what} (events: {','.join(self.names())}; stderr: {' | '.join(self.stderr[-5:])})",
                   timeout=timeout)
        return found[0]

    def wait_event(self, name: str, timeout: float = 15.0, **fields: Any) -> dict:
        return self.wait_for(lambda e: e.get("event") == name and all(e.get(k) == v for k, v in fields.items()),
                             f"event {name} {fields or ''}", timeout)

    def wait_exit(self, timeout: float = 20.0) -> int:
        try:
            rc = self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            raise AssertionError(f"device-cli did not exit within {timeout}s (events: {','.join(self.names())}; "
                                 f"stderr: {' | '.join(self.stderr[-8:])})")
        self._out.join(timeout=2)
        self._err.join(timeout=2)
        return rc

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
