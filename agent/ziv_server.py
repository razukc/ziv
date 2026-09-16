"""agent/ziv_server.py — Ziv relay v1: the phone as the dev band, with memory.

Relay v0 proved the loop; v1 gives the wearer durable state (see
``agent/ziv_store.py``): a persistent message inbox (messages that arrive
with no band attached are stored and offered on the next attach — never
silently dropped) and per-wearer memory (the playback-pace preference,
clamped into the spec's envelope).

The wrist pin does not exist yet; boards ship later. Until then the phone is
the dev band: a small PWA (agent/ziv_client/index.html) connects to this
server's WebSocket and renders the relay's turn events through the Vibration
API, using the *same* timing derivation as the firmware (the generated module
``tools/haptic_timing_gen.py``, served over ``/api/ziv/timing``) — zero
hand-copied numbers.

What this server owns (relay v1 — the loop the plan's MVP needs):

* ``/ws`` — the device transport. A phone connects once; every
  wearer-visible event is pushed as one JSON frame
  ``{"type": "haptic", "pattern": "<pattern id>", "ms": [...]}`` where ``ms``
  is the exact ``vibrate()`` pattern computed from the timing module. A
  ``{"type": "text", ...}`` frame carries narration for the demo's on-screen
  log.
* ``POST /api/ziv/message`` — one inbound message through the real seam:
  the process-wide ``MessageGate`` decides play-now vs cue-and-queue
  (invariant 4 — a message arriving mid-turn queues, it never barges),
  and an arrival when the replay queue is full (``MessageGate.MAX_QUEUED``)
  is rejected with 429 — bounded memory; the sender is told no, loudly,
  ``TurnTimeline`` emits the journey (cue → ``processing`` → playing →
  ``end-of-message`` → release), and the pump pushes each event's pattern to
  the WS. Fake-model mode sleeps ``ZIV_FAKE_MODEL_SECONDS`` (default 3 s) so
  the phone visibly feels the ``processing`` ellipsis instead of a turn that
  is instantly done. Content cells are then spelled one cell at a time at
  the wearer's cell-gap pace, and the close + release follow.
* ``GET /api/ziv/timing`` — the generated timing module serialized: the
  client bootstraps its vibrate patterns from the same source the firmware
  header was generated from (plan §4: structure universal).
* ``POST /inject/audio`` — the week-1 Omni spike's seam, now real: the PWA
  records the mic (MediaRecorder) and posts it as ``audio_b64``; the relay
  transcribes it with Nemotron-3-Nano-Omni on Nebius Token Factory (guarded
  by ``NEBIUS_API_KEY`` — without a key the endpoint answers 503) and runs
  the same turn a message would take. ``{"simulate": "<text>"}`` keeps the
  keyless stub path for hermetic demos.
* ``GET/DELETE /api/ziv/inbox`` — the persistent inbox: pending messages
  oldest-first, cap enforced; DELETE lets the wearer discard everything.
* ``GET/POST /api/ziv/prefs`` — the wearer's cell-gap preference (clamped
  into the spec envelope: structure universal, parameters personal).
* ``GET /api/ziv/health`` — liveness, attached devices, inbox/prefs state,
  queue-rejection telemetry (the 429s the relay has handed out: cumulative
  count, last refusal reason, and a per-minute rate so a spike is visible
  at a glance), turn telemetry, and any corrupt-store reports.

Auth: when ``ZIV_RELAY_TOKEN`` is set, WS connections must present it
(``?token=``) and HTTP event endpoints must carry ``Authorization: Bearer``.
Unset (default) is open — this is a LAN dev relay, not a deployment.

Run: ``python agent/ziv_server.py`` (port 8787); the dev band URL is then
``http://<lan-ip>:8787/ziv_client/index.html`` opened on the phone.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

# The shared layer + the seam (same sys.path dance as the tests: this module
# may be run as a script from the repo root or imported as agent.ziv_server).
_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import haptic_timing_gen as timing  # noqa: E402  (generated consumer)
from ports import TelemetryRing  # noqa: E402
from ziv_relay import (  # noqa: E402
    PATTERN_END_OF_MESSAGE,
    PATTERN_ERROR,
    PATTERN_MESSAGE_CUE,
    PATTERN_PROCESSING,
    MessageGate,
    TurnTimeline,
)
from ziv_store import INBOX_CAP, MessageInbox, WearerMemory  # noqa: E402

FAKE_MODEL_SECONDS = float(os.environ.get("ZIV_FAKE_MODEL_SECONDS", "3.0"))
ZIV_RELAY_TOKEN = os.environ.get("ZIV_RELAY_TOKEN", "")
ZIV_PORT = int(os.environ.get("ZIV_PORT", "8787"))

# The Omni spike (plan §7 week 1): the same credentials/base the repo's
# SkillForge agent already uses (``agent/reasoning_agent.py``). The model is
# audio-in/text-out — one model transcribes *and* understands (plan §2).
NEBIUS_API_KEY = os.environ.get("NEBIUS_API_KEY", "")
NEBIUS_BASE_URL = os.environ.get(
    "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"
)
ZIV_OMNI_MODEL = os.environ.get("ZIV_OMNI_MODEL", "nvidia/Nemotron-3-Nano-Omni")
_OMNI_PROMPT = (
    "Transcribe this audio clip. Reply with only the words that were "
    "spoken, nothing else."
)

app = FastAPI(title="Ziv relay v1 (dev band + memory)", version="0.2.0")

# Turns recorded ring — the relay's own telemetry, surfaced in health.
_telemetry = TelemetryRing(maxlen=20, recent_tail=10)

# The wearer's durable state (relay v1): survives restarts, gitignored.
memory = WearerMemory()
inbox = MessageInbox()


# ---------------------------------------------------------------------------
# Frame helpers — the wire vocabulary the PWA renders
# ---------------------------------------------------------------------------

def vibrate_pattern(pattern_id: str) -> list[int]:
    """The ``vibrate([buzz, gap, ...])`` pattern for one attention pattern id.

    Inverted against the spec's shape (buzz on, gap off), tail gap included —
    the tail silence is what makes end-of-message's close land as an *end*.
    Computed from the generated module, never hand-copied.
    """
    out: list[int] = []
    for buzz_ms, gap_ms in timing.pattern_beats(pattern_id):
        out.append(buzz_ms)
        out.append(gap_ms)
    return out


def haptic_frame(pattern_id: str, why: str = "") -> dict[str, Any]:
    """One wearer-visible haptic event as a wire frame."""
    return {
        "type": "haptic",
        "pattern": pattern_id,
        "ms": vibrate_pattern(pattern_id),
        "why": why,
    }


# ---------------------------------------------------------------------------
# Device hub: one or more phones attached over /ws
# ---------------------------------------------------------------------------

@dataclass
class DeviceHub:
    """Attached dev-band phones and the send discipline.

    One wrist, one playback loop — but during the dev phase a laptop browser
    may be attached next to the phone, so frames fan out to every connected
    device. Haptic frames are fire-and-forget by design: haptics are not
    request/response, and one slow or dead client must never stall the turn
    pump.
    """

    devices: list[WebSocket] = field(default_factory=list)

    async def attach(self, ws: WebSocket) -> None:
        self.devices.append(ws)

    def detach(self, ws: WebSocket) -> None:
        if ws in self.devices:
            self.devices.remove(ws)

    @property
    def count(self) -> int:
        return len(self.devices)

    async def broadcast(self, frame: dict[str, Any]) -> None:
        """Push one frame to every attached device; drop the dead ones.

        A hard-dead socket raises on send; the device is detached and the
        turn continues. One dead tab cannot stall the wrist.
        """
        if not self.devices:
            return
        dead: list[WebSocket] = []
        for ws in list(self.devices):
            try:
                await ws.send_text(json.dumps(frame, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.detach(ws)


hub = DeviceHub()


class _NoDevices(RuntimeError):
    pass


async def _push(frame: dict[str, Any]) -> None:
    if hub.count == 0:
        raise _NoDevices(
            "no dev band attached (open /ziv_client/index.html on the phone)"
        )
    await hub.broadcast(frame)


# ---------------------------------------------------------------------------
# Auth (optional; open by default on the LAN)
# ---------------------------------------------------------------------------

def _authorized_websocket(token: str | None) -> bool:
    if not ZIV_RELAY_TOKEN:
        return True
    return token == ZIV_RELAY_TOKEN


def _authorized_http(authorization: str | None) -> None:
    if not ZIV_RELAY_TOKEN:
        return
    if authorization != f"Bearer {ZIV_RELAY_TOKEN}":
        raise HTTPException(status_code=401, detail="bad or missing bearer token")


# ---------------------------------------------------------------------------
# The turn pump: gate + timeline → WS frames (the relay's event loop, live)
# ---------------------------------------------------------------------------

# One gate for the whole process: the wrist has one haptic channel, so the
# queue-don't-interrupt policy is server-global, not per-request. A message
# arriving while a turn is playing gets the cue-only path and queues, and its
# content replays after the current turn's close — the plan's invariant 4,
# now live between two HTTP calls.
gate = MessageGate()

# The playback loop is also single: only one turn pump may drive the wrist at
# a time. A second request queues behind this lock (and behind the gate, once
# it starts).
_turn_lock = asyncio.Lock()


class _RejectionStats:
    """Operator-visible telemetry for the refusals the relay hands out.

    Every ``message:rejected`` the gate returns (surfaced as HTTP 429) is
    counted here with its reason and a wall-clock timestamp, so health can
    answer "how often is the relay saying no?". Cumulative on purpose: the
    count is a rate signal over the server's life, not a consume-once report
    (unlike the corrupt-store lists, which health drains).

    A growing total hides a spike in the middle digit, so the snapshot also
    carries a per-minute rate: how many rejections landed in the last 60 s.
    Recent timestamps live in a bounded deque (monotonic clock, lazily
    pruned on read — no background task); the bound keeps a rejection flood
    from growing memory without bound.
    """

    #: Width of the rate window (seconds) and its hard cap on remembered
    #: timestamps — a flood beyond the cap reads as "at least this many",
    #: which is all a spike signal needs.
    WINDOW_S = 60
    WINDOW_MAX = 5000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.count = 0
        self.last_reason: str | None = None
        self.last_at: str | None = None
        self._recent: deque[float] = deque()

    def record(self, reason: str) -> None:
        with self._lock:
            self.count += 1
            self.last_reason = reason
            self.last_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._recent.append(time.monotonic())
            if len(self._recent) > self.WINDOW_MAX:
                self._recent.popleft()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cutoff = time.monotonic() - self.WINDOW_S
            while self._recent and self._recent[0] <= cutoff:
                self._recent.popleft()
            return {
                "count": self.count,
                "per_minute": len(self._recent),
                "window_s": self.WINDOW_S,
                "last_reason": self.last_reason,
                "last_at": self.last_at,
            }

    def reset(self) -> None:
        with self._lock:
            self.count = 0
            self.last_reason = None
            self.last_at = None
            self._recent.clear()


queue_rejections = _RejectionStats()


def _effective_cell_gap_ms() -> int:
    """The wearer's pace preference, clamped into the spec's envelope.

    The spec owns the envelope (structure universal); the wearer owns the
    value inside it (parameters personal). A hand-edited or stale file
    cannot put the pace outside the envelope the firmware knows.
    """
    raw = memory.get(WearerMemory.PREF_CELL_GAP, timing.CELL_GAP_DEFAULT_MS)
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = timing.CELL_GAP_DEFAULT_MS
    return max(timing.CELL_GAP_MIN_MS, min(timing.CELL_GAP_MAX_MS, v))


async def _play_cells_and_close(text: str, *, note: str | None = None) -> int:
    """Content on the motors: the cell frames, the dwell, the close.

    Shared by the turn pump (after its processing phase) and by inbox
    delivery (a stored message has nothing to compute — no fake wait).
    Returns the number of cells played.
    """
    cells = [
        {"ch": ch, "ms": timing.cell_ms(ch)}
        for ch in text.lower()
        if "a" <= ch <= "z"
    ][:timing.SPELL_MAX_LETTERS]
    label = f"queued: {text}" if note else f"message: {text}"
    await _push({"type": "text", "text": label, "chars": cells})
    gap = _effective_cell_gap_ms() / 1000.0
    for cell in cells:
        await _push({"type": "cell", "ch": cell["ch"], "ms": cell["ms"]})
        await asyncio.sleep(cell["ms"] / 1000.0 + gap)
    await _push(haptic_frame(PATTERN_END_OF_MESSAGE, why="close"))
    return len(cells)


async def _transcribe_omni(audio_b64: str, mime: str) -> str:
    """One Token Factory Omni call: audio in, transcript text out.

    OpenAI-compatible chat completions with an ``input_audio`` content part
    (base64 data URL), the same credentials/base the repo's SkillForge agent
    uses. Raises ``HTTPException(502)`` with the provider's words on any
    failure — the caller decides the wearer-visible path (the spike's
    ``long-buzz`` error pattern, not silence).
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover — httpx ships with fastapi
        raise HTTPException(status_code=500, detail="httpx unavailable") from exc
    payload = {
        "model": ZIV_OMNI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _OMNI_PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": mime},
                    },
                ],
            }
        ],
        "max_tokens": 512,
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {NEBIUS_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                NEBIUS_BASE_URL.rstrip("/") + "/chat/completions",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Token Factory unreachable: {exc}",
        ) from exc
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token Factory error {resp.status_code}: {resp.text[:300]}",
        )
    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Token Factory reply had no transcript",
        ) from exc
    text = str(text).strip()
    if not text:
        raise HTTPException(status_code=502, detail="Omni heard nothing (empty transcript)")
    return text


async def deliver_inbox_one() -> dict[str, Any] | None:
    """Deliver the oldest pending inbox message as its own full event.

    Marked delivered only *after* the close plays — a band vanishing
    mid-delivery leaves the message pending (redelivery, never loss).
    Serialized behind the turn lock: the *peek* happens inside the lock too,
    so two transports attaching at once cannot both pick up the same entry
    and play it twice — the second waits, then peeks the next one.
    """
    async with _turn_lock:
        entry = inbox.peek_one()
        if entry is None:
            return None
        await _push(haptic_frame(PATTERN_MESSAGE_CUE, why="from your inbox"))
        await _play_cells_and_close(str(entry.get("text", "")), note=True)
        inbox.mark_delivered(entry)
    return entry


async def run_message_turn(text: str, *, source: str = "message") -> dict[str, Any]:
    """One inbound message through the real seam, out over the WS.

    The ordering is TurnTimeline's, not this function's: the opening kind
    cue, ``processing`` ticks while the (fake) model works, the cue
    re-announced as content, the per-letter content cells, the
    ``end-of-message`` close, then any queued replays. Every event's pattern
    id is resolved through the generated timing module — the phone and the
    firmware play the same numbers.
    """
    # No band attached: the message is stored, not dropped — the inbox is
    # what the gate is for a turn, for days. It is offered on the next
    # attach, under the wearer's control.
    if hub.count == 0:
        entry = inbox.offer(text, source=source)
        return {
            "event": "inbox:stored",
            "stored": True,
            "inbox_pending": inbox.count(),
            "at": entry["at"],
        }

    decision = gate.admit(text)

    if decision.event_type == "message:rejected":
        # The gate said no: the replay queue is full (bounded memory, plan
        # §9). The sender gets a loud 429 with the cap — never a silent
        # drop, and the wrist feels nothing for a message that was refused.
        # The refusal is operator-visible: health counts every 429 handed out.
        queue_rejections.record(str(decision.payload.get("reason", "queue_full")))
        cap = int(decision.payload.get("cap", MessageGate.MAX_QUEUED))
        raise HTTPException(
            status_code=429,
            detail=f"message rejected: the replay queue is full ({cap} queued) — "
            "the wearer releases it after the current turn; try again later",
        )

    if decision.event_type != "message:play":
        # The gate queued it: announce now (cue only), content waits for the
        # current turn's close (invariant 4, across HTTP calls).
        await _push(haptic_frame(PATTERN_MESSAGE_CUE, why="queued"))
        return {
            "event": decision.event_type,
            "queued": True,
            "queue_len": len(gate),
        }

    async with _turn_lock:
        turn = TurnTimeline(gate, text=text)

        def frame_for(ev: Any) -> dict[str, Any]:
            et = ev.event_type
            if et == "message:play":
                return haptic_frame(PATTERN_MESSAGE_CUE, why="kind cue")
            if et == f"attention:{PATTERN_PROCESSING}":
                return haptic_frame(PATTERN_PROCESSING, why="working")
            if et == f"attention:{PATTERN_ERROR}":
                return haptic_frame(PATTERN_ERROR, why="error")
            if et == "lifecycle:playback_done":
                return haptic_frame(PATTERN_END_OF_MESSAGE, why="close")
            return {"type": "text", "text": et}

        t0 = time.monotonic()

        # The opening kind cue (invariant 1) — the turn exists.
        await _push(frame_for(turn.events[0]))

        # The model round-trip: the fake model sleeps, the timeline's clock
        # runs — waiting stays legible (invariant 3) without a timer thread.
        turn.begin_processing(now_s=0.0)
        await _push(frame_for(turn.events[-1]))
        tick = 0.05
        waited = 0.0
        while waited < FAKE_MODEL_SECONDS:
            await asyncio.sleep(tick)
            waited += tick
            ev = turn.poll(now_s=waited)
            if ev is not None:
                await _push(frame_for(ev))

        # Content on the motors: the cue re-announced (invariant 1), then the
        # message spelled as vibro-braille cells at the wearer's pace — the
        # phone literally renders the firmware's playback loop.
        turn.begin_playback()
        await _push(frame_for(turn.events[-1]))
        await _play_cells_and_close(text)

        # The close has played; the gate releases (invariants 2 + 4). Drained
        # messages replay as their own full events (cue → cells → close).
        replay = turn.finish_playback(now_s=round(time.monotonic() - t0, 1))
        drained = replay[1:]
        for ev in drained:
            replay_text = str(ev.payload.get("text", ""))
            await _push(haptic_frame(PATTERN_MESSAGE_CUE, why="queued replay cue"))
            await _play_cells_and_close(replay_text, note=True)

        _telemetry.record(
            label="message_turn",
            seconds=turn.seconds,
            retries=turn.retries,
            source=source,
            queued=len(drained),
        )
        return {
            "event": "turn_complete",
            "seconds": turn.seconds,
            "events": [ev.event_type for ev in turn.events],
            "drained": len(drained),
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_device(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    """The device transport: attach, greet, drain, detach."""
    if not _authorized_websocket(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    await hub.attach(ws)
    try:
        pending = inbox.count()
        await ws.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "spec_version": timing.SPEC_VERSION,
                    "patterns": list(timing.PATTERN_IDS),
                    "mark": timing.PREFIX_MARK,
                    "inbox_pending": pending,
                },
                ensure_ascii=False,
            )
        )
        # Relay v1: a message that arrived while no band was attached is
        # offered now, as its own full event — stored, never dropped.
        if pending:
            try:
                while await deliver_inbox_one() is not None:
                    pass
            except _NoDevices:
                pass  # the band vanished mid-delivery; entries stay pending
        # Keep the socket alive and drain client frames. The dev band never
        # sends server-meaningful frames yet; input arrives over HTTP (the
        # Omni spike's shape).
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.detach(ws)


@app.post("/api/ziv/message")
async def post_message(
    body: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """One inbound message → gate → timeline → WS frames → the wrist."""
    _authorized_http(authorization)
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    try:
        result = await run_message_turn(text, source="message")
    except _NoDevices as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/inject/audio")
async def inject_audio(
    body: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """The Omni spike's seam (week 1), now real: mic audio → transcript → turn.

    The PWA records the mic (MediaRecorder) and posts
    ``{"audio_b64": "…", "mime": "webm", "lang": "en"}`` — the relay
    transcribes with Nemotron-3-Nano-Omni on Nebius Token Factory (guarded by
    ``NEBIUS_API_KEY``: without a key the endpoint answers 503, never a
    silent failure) and the transcript takes the *same turn* a typed message
    would — cues, ticks, cells, close, queue. ``{"simulate": "<text>"}``
    keeps the keyless stub path for hermetic demos; swapping between them
    changes nothing on the phone.
    """
    _authorized_http(authorization)
    simulate = str(body.get("simulate") or "").strip()
    audio_b64 = str(body.get("audio_b64") or "").strip()
    if not simulate and not audio_b64:
        raise HTTPException(
            status_code=422,
            detail="provide 'audio_b64' (+ 'mime': webm|ogg|mp4|mp3|wav) "
            "or 'simulate' (keyless stub)",
        )
    if simulate:
        text, source = simulate, "audio_stub"
    else:
        if not NEBIUS_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="NEBIUS_API_KEY is not set — Omni transcription "
                "unavailable; use {\"simulate\": \"…\"} for the keyless stub",
            )
        mime = str(body.get("mime") or "webm").strip().lower()
        allowed = {"webm", "ogg", "mp4", "mp3", "wav"}
        if mime not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"unsupported mime {mime!r} — one of {sorted(allowed)}",
            )
        text = await _transcribe_omni(audio_b64, mime)
        source = "audio_omni"
    try:
        result = await run_message_turn(text, source=source)
    except _NoDevices as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"source": source, **result})


@app.get("/api/ziv/inbox")
def get_inbox() -> dict[str, Any]:
    """The wearer's inbox: pending messages, oldest first (the wrist shows
    them as pending until the wearer's band takes them)."""
    return {
        "pending": inbox.pending(),
        "count": inbox.count(),
        "cap": INBOX_CAP,
    }


@app.delete("/api/ziv/inbox")
def clear_inbox() -> dict[str, Any]:
    """The wearer discards everything pending — the inbox answers to them."""
    return {"cleared": inbox.clear()}


@app.get("/api/ziv/prefs")
def get_prefs() -> dict[str, Any]:
    """The wearer's playback-pace preference, clamped into the spec envelope."""
    return {
        "cell_gap_ms": _effective_cell_gap_ms(),
        "cell_gap_min_ms": timing.CELL_GAP_MIN_MS,
        "cell_gap_max_ms": timing.CELL_GAP_MAX_MS,
        "cell_gap_default_ms": timing.CELL_GAP_DEFAULT_MS,
    }


@app.post("/api/ziv/prefs")
def set_prefs(body: dict[str, Any]) -> dict[str, Any]:
    """Store the playback-pace preference (parameters are personal; the
    envelope is the spec's — values outside it are clamped, not rejected)."""
    if "cell_gap_ms" not in body:
        raise HTTPException(status_code=422, detail="cell_gap_ms is required")
    memory.set(WearerMemory.PREF_CELL_GAP, body["cell_gap_ms"])
    return get_prefs()


@app.get("/api/ziv/timing")
def get_timing() -> dict[str, Any]:
    """The generated timing module, serialized — the client's beat source.

    The phone bootstraps its vibrate patterns from the same derivation the
    firmware header was generated from (plan §4: structure is universal).
    The drift guard holds this module against the spec; the client adds no
    numbers of its own.
    """
    return {
        "spec_version": timing.SPEC_VERSION,
        "patterns": {pid: list(timing.pattern_beats(pid)) for pid in timing.PATTERN_IDS},
        "letters": {ch: timing.cell_ms(ch) for ch in timing.LETTERS},
        "letter_masks": dict(timing.LETTER_MASKS),
        "mark": timing.PREFIX_MARK,
        "mark_cells": list(timing.MARK_CELLS[timing.PREFIX_MARK]),
        "prefix_tails": dict(timing.PREFIX_TAILS),
        "prefix_breath_ms": timing.PREFIX_BREATH_MS,
        "cell_gap_ms": timing.CELL_GAP_DEFAULT_MS,
        "spell_max_letters": timing.SPELL_MAX_LETTERS,
    }


@app.get("/api/ziv/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "Ziv relay v1 (dev band + memory)",
        "devices": hub.count,
        "spec_version": timing.SPEC_VERSION,
        "fake_model_seconds": FAKE_MODEL_SECONDS,
        "auth": bool(ZIV_RELAY_TOKEN),
        "omni": {"key_set": bool(NEBIUS_API_KEY), "model": ZIV_OMNI_MODEL},
        "gate_queue": len(gate),
        "queue_rejections": queue_rejections.snapshot(),
        "inbox_pending": inbox.count(),
        "prefs": {"cell_gap_ms": _effective_cell_gap_ms()},
        "store_problems": memory.take_corrupt_files() + inbox.take_corrupt_files(),
        "turns": _telemetry.stats(),
    }


@app.get("/ziv_client/index.html")
@app.get("/ziv_client/")
def client_page() -> FileResponse:
    path = Path(__file__).resolve().parent / "ziv_client" / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="client page missing")
    return FileResponse(path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=ZIV_PORT)
