#!/usr/bin/env python
"""fake_relay.py — a small relay for the band's transport test (ladder rung 3).

A TCP line server speaking the device frames (schema/device-frames-*.json),
one JSON frame per line, on 127.0.0.1 at an ephemeral port that it prints
as its first stdout line (``port <n>``) so the runner can hand it to the C
side.  Then one scripted conversation:

  1. expect ``hello`` (the device key, the profile, the spec version, no
     last_acked, no held ids: a fresh device);
  2. reply ``hello.ack`` with prefs (pace 300, advance auto) and a resend
     list of one utterance;
  3. send ``utterance.open`` A (two words), B (body_pending) and C, then
     ``utterance.cancel`` C;
  4. on ``progress(working)`` for B, send its ``utterance.body``;
  5. after B's ``played``, send ``pref.set`` (pace 500);
  6. answer every ``ping`` with ``pong``;
  7. stop at the device's ``input.text`` and close the socket.

Every up frame is validated against the real wire models (``ziv.wire``)
when they import — the runner invokes this with the agent venv — and the
down frames are built from the same models, so the shapes are the relay's.
On exit it asserts the order the renderer contract promises:
progress(cue) → progress(word …) → progress(close) → played, per utterance,
in queue order, the ping/pong round trip, and the cancelled utterance never
heard from.  Exit 0 = PASS, 1 = FAIL (with the reason), 2 = could not run.
"""
from __future__ import annotations

import json
import socket
import sys
import time

try:
    from ziv import wire as W
    from ziv.haptics import tables as T
    SPEC_VERSION = T.SPEC_VERSION
except Exception:  # pragma: no cover - the runner uses the venv; plain python3 falls back
    W = None
    SPEC_VERSION = 4

DEVICE_KEY = "band-test-key-0123456789"
TIMEOUT_S = 60.0

RESEND_ID = "relay-resend-0001"
A_ID = "relay-open-a-0001"
B_ID = "relay-open-b-0001"
C_ID = "relay-open-c-0001"


def utt(id_: str, kind: str, words: list[str], *, prefix: bool, pending: bool = False) -> dict:
    u = {"v": 1, "id": id_, "wearer": "w_1", "kind": kind, "from": {"sender": "mira", "label": "Mira"},
         "words": words, "body_pending": pending, "spec_version": SPEC_VERSION}
    if prefix:
        u["prefix"] = {"mark": "ziv", "tail": kind}
    return u


def down(frame: dict) -> str:
    """Serialize a down frame through the wire models when available."""
    if W is not None:
        model = W.down_frame_adapter.validate_python(frame)
        return W.down_frame_adapter.dump_json(model, by_alias=True, exclude_none=True).decode()
    return json.dumps(frame, separators=(",", ":"))


def validate_up(raw: str) -> dict:
    if W is not None:
        W.up_frame_adapter.validate_json(raw)   # raises on a shape the relay would refuse
    obj = json.loads(raw)
    if not isinstance(obj, dict) or "type" not in obj:
        raise ValueError("not a frame object")
    return obj


class Conn:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = b""

    def send(self, frame: dict) -> None:
        self.sock.sendall((down(frame) + "\n").encode())

    def recv_line(self, timeout: float) -> str | None:
        self.sock.settimeout(timeout)
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                return None
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode()


def fail(msg: str) -> int:
    print(f"fake_relay: FAIL — {msg}")
    return 1


def main() -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    print(f"port {port}", flush=True)
    srv.settimeout(TIMEOUT_S)
    try:
        sock, _ = srv.accept()
    except socket.timeout:
        return fail("no device connected")
    conn = Conn(sock)

    up: list[dict] = []
    errors: list[str] = []
    body_sent = False
    pref_sent = False
    pings = 0

    # 1. hello
    raw = conn.recv_line(TIMEOUT_S)
    if raw is None:
        return fail("device closed before hello")
    try:
        hello = validate_up(raw)
    except Exception as exc:
        return fail(f"hello failed validation: {exc}: {raw}")
    if hello.get("type") != "hello":
        return fail(f"first frame is {hello.get('type')!r}, not hello")
    if hello.get("device_key") != DEVICE_KEY:
        errors.append("hello.device_key differs")
    if hello.get("profile") != "six_actuator":
        errors.append(f"hello.profile {hello.get('profile')!r}")
    if hello.get("spec_version") != SPEC_VERSION:
        errors.append(f"hello.spec_version {hello.get('spec_version')!r}")
    if hello.get("last_acked") is not None:
        errors.append("fresh device sent last_acked")
    if hello.get("held") != []:
        errors.append(f"fresh device sent held {hello.get('held')!r}")
    if hello.get("v") != 1:
        errors.append("hello.v is not 1")

    # 2. ack with a resend; 3. opens and a cancel
    conn.send({"type": "hello.ack", "v": 1, "wearer": "w_1", "device": "d_1", "spec_version": SPEC_VERSION,
               "prefs": {"pace_ms": 300, "advance": "auto"},
               "resend": [utt(RESEND_ID, "message", ["yes"], prefix=False)]})
    conn.send({"type": "utterance.open", "utterance": utt(A_ID, "message", ["taxi", "here"], prefix=True)})
    conn.send({"type": "utterance.open", "utterance": utt(B_ID, "reminder", [], prefix=False, pending=True)})
    conn.send({"type": "utterance.open", "utterance": utt(C_ID, "system", ["online"], prefix=True)})
    conn.send({"type": "utterance.cancel", "id": C_ID, "reason": "cancelled_by_sender"})

    deadline = time.monotonic() + TIMEOUT_S
    done = False
    while not done and time.monotonic() < deadline:
        try:
            raw = conn.recv_line(max(0.1, deadline - time.monotonic()))
        except socket.timeout:
            break
        if raw is None:
            errors.append("device closed before input.text")
            break
        try:
            frame = validate_up(raw)
        except Exception as exc:
            errors.append(f"up frame failed validation: {exc}: {raw[:120]}")
            continue
        up.append(frame)
        t = frame["type"]
        if t == "ping":
            pings += 1
            conn.send({"type": "pong"})
        elif t == "progress" and frame.get("id") == B_ID and frame.get("phase") == "working" and not body_sent:
            body_sent = True
            conn.send({"type": "utterance.body", "id": B_ID, "words": ["late"], "source": "live"})
        elif t == "played" and frame.get("id") == B_ID and not pref_sent:
            pref_sent = True
            conn.send({"type": "pref.set", "prefs": {"pace_ms": 500}})
        elif t == "input.text":
            done = True
    sock.close()
    srv.close()

    # the order the contract promises, per utterance, in queue order
    seq = [(f["type"], f.get("id"), f.get("phase"), f.get("word_index"))
           for f in up if f["type"] in ("progress", "played", "nack")]
    want = [
        ("progress", RESEND_ID, "cue", None), ("progress", RESEND_ID, "word", 0),
        ("progress", RESEND_ID, "close", None), ("played", RESEND_ID, None, None),
        ("progress", A_ID, "cue", None), ("progress", A_ID, "word", 0), ("progress", A_ID, "word", 1),
        ("progress", A_ID, "close", None), ("played", A_ID, None, None),
        ("progress", B_ID, "cue", None), ("progress", B_ID, "working", None), ("progress", B_ID, "word", 0),
        ("progress", B_ID, "close", None), ("played", B_ID, None, None),
    ]
    if seq != want:
        errors.append("utterance frame order differs:\n  got:  " + "\n        ".join(map(str, seq))
                      + "\n  want: " + "\n        ".join(map(str, want)))
    if any(f.get("id") == C_ID for f in up):
        errors.append("the cancelled utterance C was heard from")
    if pings < 1:
        errors.append("no ping arrived")
    controls = [f for f in up if f["type"] == "control"]
    if len(controls) != 1 or controls[0].get("action") != "replay":
        errors.append(f"expected one control(replay), got {controls}")
    prefs = [f for f in up if f["type"] == "pref.changed"]
    if len(prefs) != 1 or prefs[0].get("prefs", {}).get("pace_ms") != 350:
        errors.append(f"expected one pref.changed(pace 350), got {prefs}")
    texts = [f for f in up if f["type"] == "input.text"]
    if len(texts) != 1 or texts[0].get("words") != ["yes"] or texts[0].get("in_reply_to") != B_ID:
        errors.append(f"expected input.text ['yes'] in reply to B, got {texts}")
    if not done:
        errors.append("the conversation did not reach input.text")
    for p in [f for f in up if f["type"] == "played"]:
        if not (isinstance(p.get("started_ms"), int) and isinstance(p.get("closed_ms"), int)
                and p["closed_ms"] > p["started_ms"]):
            errors.append(f"played timestamps not monotonic: {p}")

    if errors:
        for e in errors:
            print("fake_relay: " + e)
        return fail(f"{len(errors)} problem(s) over {len(up)} up frames")
    print(f"fake_relay: PASS — {len(up)} up frames validated"
          f"{' against ziv.wire' if W is not None else ''}, order held, {pings} ping/pong")
    return 0


if __name__ == "__main__":
    sys.exit(main())
