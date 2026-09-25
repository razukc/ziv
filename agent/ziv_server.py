"""agent/ziv_server.py — Ziv relay v1: the phone as the dev band, with memory.

Relay v0 proved the loop; v1 gives the wearer durable state (see
``agent/ziv_store.py``): a persistent message inbox (messages that arrive
with no band attached are stored and offered on the next attach — never
silently dropped), a durable reminder schedule (a reminder promised for
tomorrow survives a restart tonight), and per-wearer memory (the
playback-pace preference, clamped into the spec's envelope).

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
  live queue depth vs. its cap (how close the wrist is to refusing),
  queue-rejection telemetry (the 429s the relay has handed out: cumulative
  count, last refusal reason, and a per-minute rate so a spike is visible
  at a glance), the reminder schedule's depth vs. cap plus its corrupt
  flag (consumed from the same drain as the corrupt-store list), turn
  telemetry, and any corrupt-store reports.

Auth: when ``ZIV_RELAY_TOKEN`` is set, WS connections must present it
(``?token=``) and HTTP event endpoints must carry ``Authorization: Bearer``.
Unset (default) is open — this is a LAN dev relay, not a deployment.

Run: ``python agent/ziv_server.py`` (port 8787); the dev band URL is then
``http://<lan-ip>:8787/ziv_client/index.html`` opened on the phone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

# Load .env (gitignored) before reading env vars below — the relay reads
# NEBIUS_API_KEY at import time, so the file must be loaded first.
load_dotenv()

# The shared layer + the seam (same sys.path dance as the tests: this module
# may be run as a script from the repo root or imported as agent.ziv_server).
_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import haptic_timing_gen as timing  # noqa: E402  (generated consumer)
from ziv_relay import TelemetryRing  # noqa: E402
from ziv_relay import (  # noqa: E402
    PATTERN_END_OF_MESSAGE,
    PATTERN_ERROR,
    PATTERN_MESSAGE_CUE,
    PATTERN_PROCESSING,
    MessageGate,
    TurnTimeline,
)
from ziv_store import (
    INBOX_CAP,
    MessageInbox,
    SCHEDULE_CAP,
    ScheduledReminders,
    WearerMemory,
)  # noqa: E402

#: One logger for the relay: misfires and odd states go here, not into
#: ad-hoc debug files — the telemetry ring and health stay the operator UI.
LOGGER = logging.getLogger("ziv.relay")

# ---------------------------------------------------------------------------
# Always-on (Week 3, now durable): scheduled reminders that fire unprompted.
#
# The relay's "always-on" beat is a background task that polls the schedule
# every second and fires any due reminder as its own full haptic turn on the
# phone — name-mark prefix (invariant 1: no content without a kind cue),
# then the cue, then the content cells, then the close. The wearer receives
# it without asking.
#
# The schedule itself is DURABLE (``ziv_store.ScheduledReminders`` — the
# same atomic-JSON, corrupt-tolerant, capped discipline as the inbox): a
# reminder promised for tomorrow survives a relay restart tonight. This
# module owns only the async half — claiming due reminders and playing
# them as turns.
#
# The demo beat (Week 3, day 3): schedule a reminder 20 s in the future,
# watch the phone receive it unprompted — the "acts while you're away"
# moment the track's always-on sentence needs.
# ---------------------------------------------------------------------------


async def fire_due() -> list[dict[str, Any]]:
    """Claim every due reminder and fire it as a full turn; return results.

    Claiming happens FIRST (``take_due`` removes them from the durable
    store), so a crash mid-fire means a reminder fires again on the next
    start — redelivery is the failure mode, never a silent loss (the
    inbox's rule, and now the schedule's too). No phone attached: the
    reminder is offered to the inbox (never lost, same contract as an
    inbound message) and reported as a misfire reason, not an error.
    """
    fired: list[dict[str, Any]] = []
    for r in scheduled.take_due():
        try:
            await run_message_turn(
                r["text"], source=r["source"], prefix_mark="reminder"
            )
            fired.append({**r, "fired": True, "fired_at": time.time()})
        except _NoDevices:
            # No phone attached: store as inbox entry so it's delivered on
            # the next attach (never lost, same contract as inbound msg).
            inbox.offer(r["text"], source=r["source"])
            fired.append(
                {**r, "fired": False,
                 "reason": "no_device_attached_stored_in_inbox"}
            )
        except Exception as exc:
            fired.append({**r, "fired": False, "error": str(exc)})
    return fired


async def schedule_loop(*, poll_s: float = 1.0) -> None:
    """Background task: poll and fire due reminders forever."""
    while True:
        await asyncio.sleep(poll_s)
        try:
            fired = await fire_due()
            now = time.time()
            for r in fired:
                _telemetry.record(
                    label="scheduled_reminder_fired" if r.get("fired")
                    else "scheduled_reminder_misfired",
                    seconds=now - (r.get("fire_at", now)),
                    source=r.get("source", "scheduled"),
                )
                if not r.get("fired"):
                    LOGGER.warning(
                        "scheduled_reminder_misfired id=%s reason=%s",
                        r.get("id"),
                        r.get("reason") or r.get("error") or "unknown",
                    )
        except Exception:
            pass  # the loop stays up; one bad reminder must not kill it


#: The durable schedule (ziv_store) + its fire loop (started in the app's
#: lifespan so it shares the app's event loop).
scheduled = ScheduledReminders()
_schedule_task: asyncio.Task[None] | None = None


async def run_scheduled_reminder(text: str) -> dict[str, Any]:
    """One unprompted reminder — kept as the prefix-marked path's name.

    The mark + kind tail + breath now live in ``_play_prefix_mark`` and run
    inside ``run_message_turn``'s turn lock (so no message can interleave
    between the name and what it announces); the scheduler's fire loop
    passes ``prefix_mark="reminder"`` and lands here for the same shape.
    """
    return await run_message_turn(text, source="scheduled", prefix_mark="reminder")


async def _play_prefix_mark(kind: str, text: str) -> None:
    """The name-mark prefix before an unsolicited event (plan §4 invariant 1):
    the wearer learns who is calling before the content arrives.

    Shape: Z-I-V spelled as cells at the wearer's pace, the kind's tail
    pattern (``PREFIX_TAILS`` — the reminder's triple-pulse), then a breath
    before the turn's own kind cue. Driven INSIDE the caller's turn lock,
    so nothing can interleave between the name and what it announces.
    """
    mark = list(timing.MARK_CELLS[timing.PREFIX_MARK])
    tail_id = timing.PREFIX_TAILS.get(kind, "triple-pulse")
    cells = [{"ch": ch, "ms": timing.cell_ms(ch)} for ch in mark]
    # Narration first: the wire log gets the words, the cells box gets the
    # mark's letters to light up as each cell frame lands.
    await _push({"type": "text", "text": f"{kind}: {text}", "chars": cells})
    cell_gap = _effective_cell_gap_ms() / 1000.0
    for cell in cells:
        await _push({"type": "cell", "ch": cell["ch"], "ms": cell["ms"]})
        await asyncio.sleep(cell["ms"] / 1000.0 + cell_gap)
    await _push(haptic_frame(tail_id, why=f"{kind} mark"))
    await asyncio.sleep(
        sum(buzz + gap for buzz, gap in timing.pattern_beats(tail_id)) / 1000.0
    )
    # The breath: a beat of silence between the mark and what it announces.
    await asyncio.sleep(timing.PREFIX_BREATH_MS / 1000.0)


FAKE_MODEL_SECONDS = float(os.environ.get("ZIV_FAKE_MODEL_SECONDS", "3.0"))
ZIV_RELAY_TOKEN = os.environ.get("ZIV_RELAY_TOKEN", "")
ZIV_PORT = int(os.environ.get("ZIV_PORT", "8787"))

# The Omni spike (plan §7 week 1): Nebius Token Factory credentials
# (NEBIUS_API_KEY), the standard OpenAI-compatible env pattern. The model is
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

# Lifespan: start the always-on schedule loop when the app starts and stop
# it when the app shuts down — the loop shares the app's running event loop,
# so ``asyncio.create_task`` is safe here (unlike calling it at import time).
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schedule_task
    _schedule_task = asyncio.create_task(schedule_loop(poll_s=1.0))
    try:
        yield
    finally:
        if _schedule_task is not None and not _schedule_task.done():
            _schedule_task.cancel()
            try:
                await _schedule_task
            except (asyncio.CancelledError, RuntimeError):
                pass


app = FastAPI(
    title="Ziv relay v1 (dev band + memory + schedule)",
    version="0.3.0",
    lifespan=lifespan,
)


@app.post("/api/ziv/schedule")
async def schedule_reminder(body: dict[str, Any]) -> JSONResponse:
    """Schedule a reminder to fire at a specific epoch time (seconds)."""
    fire_at = float(body.get("fire_at", 0))
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    if fire_at <= time.time():
        raise HTTPException(status_code=422, detail="fire_at must be in the future")
    rem = scheduled.add(fire_at, text)
    return JSONResponse(
        {
            "scheduled": True,
            **rem,
            "fire_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(rem["fire_at"])
            ),
        }
    )


@app.get("/api/ziv/schedule")
async def list_schedule() -> JSONResponse:
    """List scheduled reminders (id, fire_at, text, source)."""
    return JSONResponse({"reminders": scheduled.list_all()})


@app.delete("/api/ziv/schedule")
async def clear_schedule() -> JSONResponse:
    """Cancel all scheduled reminders."""
    n = scheduled.clear()
    return JSONResponse({"cleared": n})


@app.get("/api/ziv/ready")
async def ready() -> dict[str, Any]:
    """Health-plus: liveness + the schedule + the always-on loop state.

    The always-on demo beat reads this to show the scheduled reminder
    pending before it fires — proof the relay planned to act while nobody
    was chatting.
    """
    return {
        "status": "ok",
        "service": "Ziv relay v1 (dev band + memory + schedule)",
        "schedule": {
            "pending": scheduled.list_all(),
            "loop_running": _schedule_task is not None and not _schedule_task.done(),
        },
    }



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


async def _announce_error(why: str) -> None:
    """The error long-buzz for a turn that dies before it starts.

    The spike's loud-not-silent rule: a failed transcription is not dead
    air — the wrist feels the long-buzz (an attention beat, the same class
    as the queue cue) and the wire log gets the words. No band attached:
    nothing to play on; the HTTP error still answers the sender.
    """
    try:
        await _push(haptic_frame(PATTERN_ERROR, why=why))
        await _push({"type": "text", "text": f"error: {why}"})
    except _NoDevices:
        pass


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


async def _play_cells_and_close(
    text: str, *, note: str | None = None, free_fn=None
) -> int:
    """Content on the motors: the cell frames, the dwell, the close.

    Shared by the turn pump (after its processing phase) and by inbox
    delivery (a stored message has nothing to compute — no fake wait).
    Returns the number of cells played.

    ``free_fn`` marks the close that truly frees the wrist: it is evaluated
    LAZILY, at the close push — after every cell dwell — because messages
    arriving mid-content queue during exactly those dwells (an eager flag
    computed at call time would mark a close "free" while fills were still
    landing). After the close it gates, the server plays nothing more for
    this turn. The dev band fires its armed redial on exactly this frame —
    a close that merely ends one replay of a drain sequence would queue the
    redial behind the remaining replays, so "the close lands on the wire"
    must mean the *last* one.
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
    close = haptic_frame(PATTERN_END_OF_MESSAGE, why="close")
    if free_fn is not None and free_fn():
        close["free"] = True
    await _push(close)
    return len(cells)


async def _transcribe_omni(audio_b64: str, mime: str) -> str:
    """One Token Factory Omni call: audio in, transcript text out.

    OpenAI-compatible chat completions with an ``input_audio`` content part
    (base64 data URL), the standard Token Factory
    credentials/base. Raises ``HTTPException(502)`` with the provider's words on any
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

    Every replay is a self-naming turn: the entry's source picks the mark
    kind (a stored reminder replays with the reminder's triple-pulse tail,
    any other stored message with the message's double-tap), so the wrist
    feels who is calling — and what kind of event it was — before the
    stored content arrives.
    """
    async with _turn_lock:
        entry = inbox.peek_one()
        if entry is None:
            return None
        source = str(entry.get("source", "message"))
        # Inbox sources are storage origins, not mark kinds: map them —
        # a reminder stored while away replays as a reminder; everything
        # else (typed, transcribed) replays as a message.
        kind = "reminder" if source == "scheduled" else "message"
        await _play_prefix_mark(kind, str(entry.get("text", "")))
        await _play_cells_and_close(str(entry.get("text", "")), note=True)
        inbox.mark_delivered(entry)
    return entry


async def run_message_turn(
    text: str, *, source: str = "message", prefix_mark: str | None = None
) -> dict[str, Any]:
    """One inbound message through the real seam, out over the WS.

    The ordering is TurnTimeline's, not this function's: the opening kind
    cue, ``processing`` ticks while the (fake) model works, the cue
    re-announced as content, the per-letter content cells, the
    ``end-of-message`` close, then any queued replays. Every event's pattern
    id is resolved through the generated timing module — the phone and the
    firmware play the same numbers.

    ``prefix_mark``: an UNSOLICITED turn opens with the name-mark prefix
    (``_play_prefix_mark``) inside the same turn lock — the scheduler's
    reminders pass ``"reminder"`` so the wrist feels who is calling before
    the reminder's content arrives.
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
        # An unsolicited turn names itself first (plan §4 invariant 1):
        # the mark plays inside this lock, so no message can interleave
        # between the name and the content it announces.
        if prefix_mark is not None:
            await _play_prefix_mark(prefix_mark, text)

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

        # Content on the motors (the gate stays "playing" through every
        # cell dwell — a message arriving mid-content queues, invariant 4).
        # The wrist is freed by the LAST close of the sequence: the main
        # close when the queue holds nothing AT THE CLOSE PUSH, else the
        # final replay's close below. The flag is evaluated lazily (see
        # _play_cells_and_close) — after the dwells, where fills land.
        await _play_cells_and_close(text, free_fn=lambda: len(gate) == 0)

        # The close has played; the gate releases (invariants 2 + 4) and the
        # drained messages replay as their own full events (cue → cells →
        # close), the last one carrying the ``free`` marker the dev band
        # fires its armed redial on.
        replay = turn.finish_playback(now_s=round(time.monotonic() - t0, 1))
        drained = replay[1:]
        for idx, ev in enumerate(drained):
            replay_text = str(ev.payload.get("text", ""))
            await _push(haptic_frame(PATTERN_MESSAGE_CUE, why="queued replay cue"))
            await _play_cells_and_close(
                replay_text, note=True,
                free_fn=lambda idx=idx, n=len(drained): idx == n - 1,
            )

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
        try:
            text = await _transcribe_omni(audio_b64, mime)
        except HTTPException as exc:
            # The error long-buzz, not silence (the spike's loud-not-silent
            # rule): the transcription died before a turn could start, so
            # the wrist feels the attention beat now.
            await _announce_error(f"transcription failed ({exc.status_code})")
            raise
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
    # Every load that can DISCOVER corruption runs BEFORE the single drain:
    # a corrupt file is found (and reported) by the depth/count/prefs reads,
    # so the drain below captures all of it — one snapshot, the flag and
    # the store_problems list can never disagree, and the consume-once
    # report is consumed exactly once.
    schedule_pending = scheduled.count()
    inbox_pending = inbox.count()
    prefs = {"cell_gap_ms": _effective_cell_gap_ms()}
    corrupt = (
        memory.take_corrupt_files()
        + inbox.take_corrupt_files()
        + scheduled.take_corrupt_files()
    )
    return {
        "status": "ok",
        "service": "Ziv relay v1 (dev band + memory)",
        "devices": hub.count,
        "spec_version": timing.SPEC_VERSION,
        "fake_model_seconds": FAKE_MODEL_SECONDS,
        "auth": bool(ZIV_RELAY_TOKEN),
        "omni": {"key_set": bool(NEBIUS_API_KEY), "model": ZIV_OMNI_MODEL},
        "gate_queue": len(gate),
        "gate_queue_cap": MessageGate.MAX_QUEUED,
        "queue_rejections": queue_rejections.snapshot(),
        "inbox_pending": inbox_pending,
        # The schedule gets the badge treatment too: depth vs. cap (how
        # close it is to dropping the oldest reminder), and the corrupt
        # flag read from the one shared drain above.
        "schedule_pending": schedule_pending,
        "schedule_cap": SCHEDULE_CAP,
        "schedule_corrupt": "schedule" in corrupt,
        "prefs": prefs,
        "store_problems": corrupt,
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
