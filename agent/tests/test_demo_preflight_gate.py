"""Hermetic coverage for the demo pre-flight gate.

``scripts/demo_preflight.sh`` decides whether a take may start, and the only
things that make it safe are its exit codes and the promise that a failed gate
does not leave a probe reminder to play over the demo. Both were proven by
hand against a live origin before this module existed: the pass and each
refusal path were re-derived in a scratch harness, which is exactly the kind
of evidence that disappears with the shell that produced it.

These tests stand a stub relay on a loopback port and drive the real probe at
it, so the gate's matrix runs on every push with no network, no key, and no
band. The stub answers the four routes the probe reads (health, ready,
control, schedule) and can be told to stay stuck, misfire, refuse the schedule
call, or fail a surface. Two tests then run the actual bash wrapper, because
the wrapper is what an operator types and its exit code is the contract the
runbook keys off.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ziv_loop_liveness_probe as probe  # noqa: E402

STAMP_BEFORE = "2026-10-25T15:24:50.97Z"
STAMP_AFTER = "2026-10-26T05:53:21.714953Z"
OURS = "probe-1"
BASH = shutil.which("bash")


class _Relay:
    """Mutable stub-relay state; one instance per test."""

    def __init__(self) -> None:
        self.base = ""
        self.loop = {"health": True, "ready": True, "control": True}
        self.devices: int | None = 1
        self.inbox_pending = 0
        self.gate_queue = 0
        self.rows: list[dict[str, Any]] = []
        self.last_fire_at = STAMP_BEFORE
        # fire: the loop takes the reminder and stamps a new fire;
        # misfire: it disappears without a stamp; never: it stays pending.
        self.mode = "fire"
        self.post_status = 200
        self.failures: dict[str, int] = {}
        self.posts = 0
        self.deletes = 0
        self.posted = False


def _handler(state: _Relay) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # keep pytest output clean
            return

        def _send(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length)) if length else {}

        def _refuse_if_asked(self) -> bool:
            status = state.failures.get(self.path)
            if status is None:
                return False
            self._send(status, {"detail": "unavailable"})
            return True

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if self._refuse_if_asked():
                return
            if self.path == "/api/ziv/health":
                self._send(200, {
                    "schedule_loop": {
                        "running": state.loop["health"],
                        "last_fire_at": state.last_fire_at,
                    },
                    "devices": state.devices,
                    "inbox_pending": state.inbox_pending,
                    "gate_queue": state.gate_queue,
                })
                return
            if self.path == "/api/ziv/ready":
                if state.posted:
                    if state.mode == "fire":
                        state.rows = [r for r in state.rows if r["id"] != OURS]
                        state.last_fire_at = STAMP_AFTER
                    elif state.mode == "misfire":
                        state.rows = [r for r in state.rows if r["id"] != OURS]
                self._send(200, {
                    "schedule": {
                        "loop_running": state.loop["ready"],
                        "pending": [dict(r) for r in state.rows],
                    },
                })
                return
            if self.path == "/api/ziv/control":
                self._send(200, {
                    "loop": {
                        "running": state.loop["control"],
                        "started": True,
                        "iface": True,
                    },
                })
                return
            if self.path == "/api/ziv/schedule":
                self._send(200, {"reminders": [dict(r) for r in state.rows]})
                return
            self._send(404, {"detail": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/ziv/schedule":
                self._send(404, {"detail": "not found"})
                return
            body = self._body()
            state.posts += 1
            state.posted = True
            if state.post_status != 200:
                self._send(state.post_status, {"detail": "refused"})
                return
            state.rows.append({
                "id": OURS,
                "fire_at": body.get("fire_at"),
                "text": body.get("text"),
            })
            self._send(200, {
                "scheduled": True,
                "id": OURS,
                "fire_at": body.get("fire_at"),
            })

        def do_DELETE(self) -> None:  # noqa: N802
            if self.path != "/api/ziv/schedule":
                self._send(404, {"detail": "not found"})
                return
            state.deletes += 1
            cleared = len(state.rows)
            state.rows.clear()
            self._send(200, {"cleared": cleared})

    return Handler


@pytest.fixture()
def relay():
    state = _Relay()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    # A short poll interval keeps 17 fixtures' teardown from adding seconds.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    state.base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def gate(relay, monkeypatch):
    """Point the real probe at the stub relay; return the stub for assertions."""
    monkeypatch.setattr(probe, "RELAY", relay.base)
    return relay


def _run_gate(**overrides: Any) -> tuple[int, str, dict[str, Any]]:
    """Run the wait-for-fire gate with short waits and map it to an exit code."""
    kwargs: dict[str, Any] = {
        "wait_for_fire": True,
        "fire_in": 0,
        "wait_timeout": 2,
    }
    kwargs.update(overrides)
    result = probe.probe(**kwargs)
    code, reason = probe.gate(result)
    return code, reason, result


def _closed_port() -> int:
    """A loopback port nothing is listening on (bind, read, release)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_a_proven_fire_passes_and_leaves_no_reminder(gate):
    code, reason, result = _run_gate()

    assert code == 0, reason
    assert gate.posts == 1
    assert gate.deletes == 0
    assert result["fired"] is True
    assert result["reminder_cleared"] is True
    assert result["last_fire_at_after_wait"] == STAMP_AFTER
    assert gate.rows == []


@pytest.mark.parametrize(
    ("surface", "reported"),
    [
        ("health", "/api/ziv/health schedule_loop.running"),
        ("ready", "/api/ziv/ready schedule.loop_running"),
        ("control", "/api/ziv/control loop.running"),
    ],
)
def test_a_stopped_surface_blocks_before_scheduling(gate, surface, reported):
    """A stopped loop must fail before the POST — a reminder left behind
    would fire later, possibly mid-take."""
    gate.loop[surface] = False

    code, reason, result = _run_gate()

    assert code == 1
    assert reported in reason
    assert result["skipped"] == "loop_not_running"
    assert gate.posts == 0


def test_an_unreadable_surface_fails_closed(gate):
    """Unreadable is not the same as stopped, and neither may pass."""
    gate.failures["/api/ziv/health"] = 503

    code, reason, result = _run_gate()

    assert code == 2
    assert "cannot read /api/ziv/health" in reason
    assert gate.posts == 0


def test_an_unreachable_origin_fails_closed(monkeypatch):
    monkeypatch.setattr(probe, "RELAY", f"http://127.0.0.1:{_closed_port()}")

    code, reason, result = _run_gate()

    assert code == 2
    assert "cannot read" in reason
    assert "schedule_request" not in result


def test_no_band_attached_fails_before_scheduling(gate):
    gate.devices = 0

    code, reason, result = _run_gate()

    assert code == 3
    assert result["skipped"] == "no_device_attached"
    assert "no band attached" in reason
    assert gate.posts == 0


@pytest.mark.parametrize("field", ["inbox_pending", "gate_queue"])
def test_a_busy_band_fails_before_scheduling(gate, field):
    """A backlog would queue the probe behind the take; refuse instead."""
    setattr(gate, field, 1)

    code, reason, result = _run_gate()

    assert code == 3
    assert result["skipped"] == "band_not_idle"
    assert "band is not idle" in reason
    assert gate.posts == 0


def test_a_rejected_schedule_fails(gate):
    gate.post_status = 500

    code, reason, result = _run_gate()

    assert code == 3
    assert "could not schedule the probe reminder (status 500)" in reason
    assert gate.posts == 1


def test_a_stuck_loop_cancels_its_own_reminder(gate):
    gate.mode = "never"

    code, reason, result = _run_gate()

    assert code == 3
    assert result["reminder_still_pending_after_wait"] is True
    assert result["cleaned_up"] is True
    assert gate.deletes == 1
    assert gate.rows == []
    assert "the probe reminder was canceled" in reason


def test_a_stuck_loop_leaves_other_reminders_alone(gate):
    """There is no per-id cancel, so cleanup must refuse to wipe a schedule
    that holds someone else's reminder — even though it then leaves its own
    behind, which the operator has to clear by hand."""
    gate.mode = "never"
    gate.rows.append({"id": "someone-else", "fire_at": 0, "text": "judge repro"})

    code, reason, result = _run_gate()

    assert code == 3
    assert result["cleaned_up"] is False
    assert gate.deletes == 0
    assert {r["id"] for r in gate.rows} == {OURS, "someone-else"}
    assert "it is still pending; clear it before the demo" in reason


def test_a_misfire_fails_without_a_new_stamp(gate):
    """Clearing alone is not proof: no band means the reminder goes to the
    inbox and no fire happens, which is exactly the state a demo must not
    start in."""
    gate.mode = "misfire"

    code, reason, result = _run_gate()

    assert code == 3
    assert result["reminder_cleared"] is True
    assert result["fired"] is False
    assert gate.deletes == 0
    assert "misfire" in reason


def _run_wrapper(relay_base: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ZIV_RELAY"] = relay_base
    env["PYTHON"] = Path(sys.executable).as_posix()
    return subprocess.run(
        [BASH or "bash", "scripts/demo_preflight.sh"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        # Pin the decode: a CI locale must not turn the wrapper's output into
        # a UnicodeDecodeError (and a missing stderr) instead of an assertion.
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


@pytest.mark.skipif(BASH is None, reason="the wrapper is a bash script")
def test_the_wrapper_passes_a_proven_fire(relay):
    done = _run_wrapper(relay.base)

    assert done.returncode == 0, done.stderr
    assert "PASS: schedule loop running" in done.stderr
    assert "preflight passed - the loop is running and fired the probe reminder" in done.stderr
    assert relay.posts == 1


@pytest.mark.skipif(BASH is None, reason="the wrapper is a bash script")
def test_the_wrapper_maps_a_stopped_loop_to_exit_1(relay):
    relay.loop["health"] = False

    done = _run_wrapper(relay.base)

    assert done.returncode == 1
    assert "DEMO BLOCKED: a surface reports the schedule loop stopped." in done.stderr
    assert relay.posts == 0


@pytest.mark.skipif(BASH is None, reason="the wrapper is a bash script")
def test_the_wrapper_maps_an_unreadable_relay_to_exit_2():
    done = _run_wrapper(f"http://127.0.0.1:{_closed_port()}")

    assert done.returncode == 2
    assert "DEMO BLOCKED: the relay could not be read at" in done.stderr


@pytest.mark.skipif(BASH is None, reason="the wrapper is a bash script")
def test_the_wrapper_maps_an_unproven_fire_to_exit_3(relay):
    relay.devices = 0

    done = _run_wrapper(relay.base)

    assert done.returncode == 3
    assert "DEMO BLOCKED: the loop says it is running but no fire was proven." in done.stderr
    assert relay.posts == 0
