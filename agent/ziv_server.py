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
  (invariant 4 — a message arriving mid-turn queues, it never barges) and
  ``message:play`` **reserves the channel for the whole turn**, model wait
  and all, so the queue-don't-interrupt policy covers the quiet stretches
  too. An arrival when the replay queue is full (``MessageGate.MAX_QUEUED``)
  is rejected with 429 — bounded memory; the sender is told no, loudly.
  ``TurnTimeline`` emits the journey (cue → ``processing`` → playing →
  ``end-of-message`` → release), and the pump pushes each event's pattern to
  the WS. Fake-model mode sleeps ``ZIV_FAKE_MODEL_SECONDS`` (default 3 s) so
  the phone visibly feels the ``processing`` ellipsis instead of a turn that
  is instantly done. Content cells are then spelled one cell at a time at
  the wearer's cell-gap pace, and the close + release follow.
* ``GET /api/ziv/timing`` — the generated timing module serialized: the
  client bootstraps its vibrate patterns from the same source the firmware
  header was generated from (plan §4: structure universal).
* ``POST /api/ziv/schedule`` — a reminder, or an *intent* the agent path
  turns into a line when it fires (see ``compose_reminder_line``): a live
  NVIDIA open model on Nebius Token Factory, whose words the phone spells.
* ``POST /inject/audio`` — the audio seam, held as asset: the PWA records
  the mic and posts ``audio_b64``. It needs an audio-capable endpoint, so it
  answers 503 unless one is configured rather than naming a model that cannot
  serve the request. ``{"simulate": "<text>"}`` is the keyless path the demo
  runs, and it takes the same turn a message would.
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
(``?token=``) and every route that can carry or reveal the wearer's content
(``/api/ziv/message``, ``/inject/audio``, ``/api/ziv/schedule``, ``/api/ziv/
ready``, ``/api/ziv/inbox``, ``/api/ziv/prefs``) must carry
``Authorization: Bearer`` — one declared dependency, so the next endpoint
added inherits the rule instead of forgetting it. ``/api/ziv/timing`` (the
generated spec), ``/api/ziv/health`` (counts and telemetry, no content) and
the client page stay open because the PWA bootstraps from them before it can
present a credential. Unset (default) is open — this is a LAN dev relay, not
a deployment.

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
import weakref
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
load_dotenv()
_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / 'agent'), str(_ROOT / 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import haptic_timing_gen as timing
from ziv_relay import TelemetryRing
from ziv_relay import PATTERN_END_OF_MESSAGE, PATTERN_ERROR, PATTERN_MESSAGE_CUE, PATTERN_PROCESSING, MessageGate, TurnTimeline
from ziv_store import INBOX_CAP, MessageInbox, SCHEDULE_CAP, ScheduledReminders, WearerMemory

class _PerLoop:
    """One asyncio primitive per running event loop.

    The relay is a single-loop server — one process, one uvicorn loop — so a
    module-level ``asyncio.Event`` / ``Lock`` is the natural shape. But the
    test suite drives this module through many short-lived loops: every
    ``asyncio.run`` in a test, and every ``TestClient`` portal, is its own
    loop, and once a primitive has been awaited in one of them, touching it
    from another raises ``RuntimeError: <...> is bound to a different event
    loop``. That made a test's outcome depend on which tests ran before it.

    Binding lazily to whichever loop touches the primitive keeps the server's
    one-loop behavior identical (the first loop gets the first instance and
    keeps it) and gives every test loop a clean, unshared instance. Entries
    are weak, so a closed loop's primitive is dropped with it. Access outside
    any loop — a test resetting state between cases, for example — uses a
    detached instance, which is only inspected or cleared there, never awaited.
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any] = weakref.WeakKeyDictionary()
        self._detached = factory()

    def current(self) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._detached
        primitive = self._by_loop.get(loop)
        if primitive is None:
            primitive = self._factory()
            self._by_loop[loop] = primitive
        return primitive


class _LoopBoundEvent:
    """``asyncio.Event`` semantics, one instance per event loop (see _PerLoop)."""

    __slots__ = ('_per_loop',)

    def __init__(self) -> None:
        self._per_loop = _PerLoop(asyncio.Event)

    def set(self) -> None:
        self._per_loop.current().set()

    def clear(self) -> None:
        self._per_loop.current().clear()

    def is_set(self) -> bool:
        return self._per_loop.current().is_set()

    async def wait(self) -> bool:
        return await self._per_loop.current().wait()

    def __repr__(self) -> str:
        return f'_LoopBoundEvent({self._per_loop.current()!r})'


class _LoopBoundLock:
    """``asyncio.Lock`` semantics, one instance per event loop (see _PerLoop)."""

    __slots__ = ('_per_loop',)

    def __init__(self) -> None:
        self._per_loop = _PerLoop(asyncio.Lock)

    async def __aenter__(self) -> None:
        await self._per_loop.current().__aenter__()

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._per_loop.current().__aexit__(*exc_info)

    def locked(self) -> bool:
        return self._per_loop.current().locked()


class ScheduleLoopIface:
    """The control surface the routes and the WS layer import.

    Pause/resume/quit here are the ONLY public handles on the always-on
    loop. Pause is a suspend, not a kill — the loop keeps its state and its
    schedule file; a reminder due while paused stays in the store and fires
    when the pause is cleared, never silently dropped. Quit ends the loop
    for good.
    """

    def __init__(self, *, pause: Callable[[], Awaitable[None]], resume: Callable[[], Awaitable[None]], quit: Callable[[], Awaitable[None]]) -> None:
        self.pause = pause
        self.resume = resume
        self.quit = quit
LOGGER = logging.getLogger('ziv.relay')

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
            text, source = (r['text'], r['source'])
            if source == 'agent':
                if agent_path_available():
                    try:
                        composed = await compose_reminder_line(r['text'])
                    except Exception as exc:
                        LOGGER.warning('compose failed for reminder %s (%s); firing verbatim', r.get('id'), exc)
                        text, source = (r['text'], 'text_echo')
                    else:
                        if composed and composed.strip():
                            text, source = (composed.strip(), 'text_live')
                        else:
                            LOGGER.warning('compose returned nothing usable for reminder %s; firing verbatim', r.get('id'))
                            text, source = (r['text'], 'text_echo')
                else:
                    source = 'text_echo'
            await run_message_turn(text, source=source, prefix_mark='reminder')
            fired.append({**r, 'text': text, 'source': source, 'fired': True, 'fired_at': time.time()})
        except _NoDevices:
            fired.append({**r, 'fired': False, 'reason': 'no_device_attached_stored_in_inbox'})
        except Exception as exc:
            fired.append({**r, 'fired': False, 'error': str(exc)})
    return fired

async def schedule_loop(*, poll_s: float=1.0, iface: ScheduleLoopIface | None=None) -> None:
    """Background task: poll and fire due reminders forever.

    The only background task the relay owns. When it is not running the
    relay still serves every HTTP route and every WS turn; it just does not
    fire reminders unprompted — the always-on path is silent until the loop
    is restarted. ``pause`` suspends polling (the loop keeps ticking but
    fires nothing) until ``resume`` clears it; ``quit`` asks it to exit and
    returns the moment it has.
    """
    global _schedule_loop_started, _schedule_loop_iface
    loop = asyncio.get_running_loop()
    _schedule_loop_started = True
    _schedule_loop_iface = ScheduleLoopIface(pause=_pause_schedule, resume=_resume_schedule, quit=_quit_schedule)
    if iface is not None:
        # An injected iface replaces the control surface, not the waiter
        # primitives: pause/stop are per-loop (created on first use by this
        # loop), so this loop already starts with fresh, clear flags.
        _schedule_loop_iface = iface
    while not _schedule_stop.is_set():
        if _schedule_pause.is_set():
            # Paused: the flag stays set until ``resume`` clears it. Waiting on
            # it directly returns immediately while set, which turns the loop
            # into a 100%-CPU spin that starves every HTTP and WS request on
            # this same loop (observed: the next request after a control
            # ``pause`` never completed). Sleep a real tick instead; wait on
            # stop so ``quit`` is still observed promptly.
            try:
                await asyncio.wait_for(_schedule_stop.wait(), timeout=poll_s)
            except asyncio.TimeoutError:
                pass
            continue
        try:
            await asyncio.wait_for(_schedule_pause.wait(), timeout=poll_s)
        except asyncio.TimeoutError:
            pass
        if _schedule_stop.is_set():
            break
        try:
            fired = await fire_due()
            now = time.time()
            for r in fired:
                _telemetry.record(label='scheduled_reminder_fired' if r.get('fired') else 'scheduled_reminder_misfired', seconds=now - r.get('fire_at', now), retries=0, source=r.get('source', 'scheduled'))
                if not r.get('fired'):
                    LOGGER.warning('scheduled_reminder_misfired id=%s reason=%s', r.get('id'), r.get('reason') or r.get('error') or 'unknown')
        except Exception:
            pass
_schedule_pause = _LoopBoundEvent()
_schedule_stop = _LoopBoundEvent()

async def _pause_schedule() -> None:
    """Suspend the schedule loop's next poll (resume wakes it)."""
    if _schedule_loop_iface is None:
        raise HTTPException(status_code=503, detail='the always-on loop has not started yet')
    _schedule_pause.set()

async def _resume_schedule() -> None:
    """Let the schedule loop poll again."""
    if _schedule_loop_iface is None:
        raise HTTPException(status_code=503, detail='the always-on loop has not started yet')
    # Clear only: re-setting it here left the loop awake (and polling in a
    # hot loop) after every resume, so ``pause`` never actually ended.
    _schedule_pause.clear()

async def _quit_schedule() -> ScheduleLoopIface | None:
    """Ask the schedule loop to exit and wait for it to have done so.

    Returns the iface the loop was using before it was torn down, so the caller
    can tell whether the loop was actually running at request time (rather than
    inferring it from a 503 vs 200 — the endpoint returns 200 with a None iface
    only when the loop never reached poll).
    """
    global _schedule_loop_iface
    fh_iface = _schedule_loop_iface
    if fh_iface is None:
        raise HTTPException(status_code=503, detail='the always-on loop has not started yet')
    _schedule_stop.set()
    _schedule_pause.set()
    _schedule_loop_iface = None
    if _schedule_task is not None and (not _schedule_task.done()):
        await _schedule_task
    return fh_iface
SCHEDULE_CONTROL = {'pause': _pause_schedule, 'resume': _resume_schedule, 'quit': _quit_schedule}
_schedule_loop_started: bool = False
_schedule_loop_iface: ScheduleLoopIface | None = None

async def _dwell(seconds: float) -> None:
    """Wait out one beat of the wearer's pace — the relay's only sleep.

    Every dwell the relay owes the wrist goes through here: the gap between
    two cells, the model's processing wait, the mark's tail and breath. The
    numbers are computed from the generated timing module upstream, so this
    is the single place where "how long did the relay actually wait" lives —
    which is what makes the pacing assertable instead of merely intended.
    (The scheduler's own poll interval is NOT a dwell and still sleeps
    directly.)

    A pause request short-circuits every dwell: the wearer's rhythm survives
    the pause exactly as it was — the next resume picks up the same turn at
    the same pending dwell, so no countdown is silently warped.
    """
    global _schedule_loop_started
    if not _schedule_loop_started:
        await asyncio.sleep(seconds)
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        remaining = deadline - loop.time()
        to_wait = min(remaining, 0.1)
        try:
            await asyncio.wait_for(_schedule_pause.wait(), timeout=to_wait)
        except asyncio.TimeoutError:
            pass
        if _schedule_stop.is_set():
            return

async def _play_prefix_mark(kind: str, text: str) -> None:
    """The name-mark prefix before an unsolicited event (plan §4 invariant 1):
    the wearer learns who is calling before the content arrives.

    Shape: Z-I-V spelled as cells at the wearer's pace, the kind's tail
    pattern (``PREFIX_TAILS`` — the reminder's triple-pulse), then a breath
    before the turn's own kind cue. Driven INSIDE the caller's turn lock,
    so nothing can interleave between the name and what it announces.
    """
    mark = list(timing.MARK_CELLS[timing.PREFIX_MARK])
    tail_id = timing.PREFIX_TAILS.get(kind, 'triple-pulse')
    cells = [{'ch': ch, 'ms': timing.cell_ms(ch)} for ch in mark]
    await _push({'type': 'text', 'text': f'{kind}: {text}', 'chars': cells})
    cell_gap = _effective_cell_gap_ms() / 1000.0
    for cell in cells:
        await _push({'type': 'cell', 'ch': cell['ch'], 'ms': cell['ms']})
        await _dwell(cell['ms'] / 1000.0 + cell_gap)
    await _push(haptic_frame(tail_id, why=f'{kind} mark'))
    await _dwell(sum((buzz + gap for buzz, gap in timing.pattern_beats(tail_id))) / 1000.0)
    await _dwell(timing.PREFIX_BREATH_MS / 1000.0)
FAKE_MODEL_SECONDS = float(os.environ.get('ZIV_FAKE_MODEL_SECONDS', '3.0'))
ZIV_RELAY_TOKEN = os.environ.get('ZIV_RELAY_TOKEN', '')
ZIV_PORT = int(os.environ.get('ZIV_PORT', '8787'))
WS_HEARTBEAT_S = float(os.environ.get('ZIV_WS_HEARTBEAT_S', '10.0'))
NEBIUS_API_KEY = os.environ.get('NEBIUS_API_KEY', '')
NEBIUS_BASE_URL = os.environ.get('NEBIUS_BASE_URL') or 'https://api.tokenfactory.nebius.com/v1/'
ZIV_TEXT_MODEL = os.environ.get('ZIV_TEXT_MODEL') or 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'
ZIV_OMNI_MODEL = os.environ.get('ZIV_OMNI_MODEL', '')
_OMNI_PROMPT = 'Transcribe this audio clip. Reply with only the words that were spoken, nothing else.'
_COMPOSE_PROMPT = 'You write the single line a vibro-braille channel plays to a deafblind wearer. Reply with that line only — no quotes, no preamble, no markdown, at most 30 characters, plain everyday words.'

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schedule_task
    _schedule_task = asyncio.create_task(schedule_loop(poll_s=1.0))
    try:
        yield
    finally:
        if _schedule_task is not None and (not _schedule_task.done()):
            _schedule_task.cancel()
            try:
                await _schedule_task
            except (asyncio.CancelledError, RuntimeError):
                pass
app = FastAPI(title='Ziv relay v1 (dev band + memory + schedule)', version='0.3.0', lifespan=lifespan)

def _authorized_websocket(token: str | None) -> bool:
    if not ZIV_RELAY_TOKEN:
        return True
    return token == ZIV_RELAY_TOKEN

def _authorized_http(authorization: str | None) -> None:
    if not ZIV_RELAY_TOKEN:
        return
    if authorization != f'Bearer {ZIV_RELAY_TOKEN}':
        raise HTTPException(status_code=401, detail='bad or missing bearer token')

def require_auth(authorization: str | None=Header(default=None)) -> None:
    """Bearer-token gate for every route that can *carry or reveal* content.

    The wearer's messages, their scheduled reminders and their preferences
    are their own: whoever may send a message may read the inbox, and
    nothing else. Applied as a route dependency so the rule is declared once
    and cannot be quietly skipped on the next endpoint added.

    What stays open, and why:

    * ``/ws`` — the device transport, gated by its own ``?token=`` (a
      WebSocket handshake cannot carry an Authorization header).
    * ``/api/ziv/timing`` — the generated spec, no wearer content; the PWA
      must bootstrap from it before it holds any credential.
    * ``/api/ziv/health`` — the operator view the PWA's queue badge polls.
      Counts, caps, model wiring and turn telemetry only; never a message's
      text. Anything added here has to keep that true.
    * ``/ziv_client/index.html`` — the client page itself, which a phone has
      to load before it can present anything.
    """
    _authorized_http(authorization)
AUTHENTICATED = [Depends(require_auth)]

@app.post('/api/ziv/schedule', dependencies=AUTHENTICATED)
async def schedule_reminder(body: dict[str, Any]) -> JSONResponse:
    """Schedule a reminder to fire at a specific epoch time (seconds).

    ``text`` is a finished line, played verbatim. ``intent`` is the agent
    path: the promise is stored as an intent, and the line is composed by the
    model when it fires. Both are durable, so both survive a restart.
    """
    fire_at = float(body.get('fire_at', 0))
    text = str(body.get('text', '')).strip()
    intent = str(body.get('intent', '')).strip()
    if not text and (not intent):
        raise HTTPException(status_code=422, detail='text (a line) or intent (composed) is required')
    if fire_at <= time.time():
        raise HTTPException(status_code=422, detail='fire_at must be in the future')
    rem = scheduled.add(fire_at, intent or text, source='agent' if intent else 'scheduled')
    return JSONResponse({'scheduled': True, **rem, 'fire_at_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(rem['fire_at']))})

@app.get('/api/ziv/schedule', dependencies=AUTHENTICATED)
async def list_schedule() -> JSONResponse:
    """List scheduled reminders (id, fire_at, text, source)."""
    return JSONResponse({'reminders': scheduled.list_all()})

@app.delete('/api/ziv/schedule', dependencies=AUTHENTICATED)
async def clear_schedule() -> JSONResponse:
    """Cancel all scheduled reminders."""
    n = scheduled.clear()
    return JSONResponse({'cleared': n})

@app.get('/api/ziv/ready', dependencies=AUTHENTICATED)
async def ready() -> dict[str, Any]:
    """Health-plus: liveness + the schedule + the always-on loop state.

    The always-on demo beat reads this to show the scheduled reminder
    pending before it fires — proof the relay planned to act while nobody
    was chatting.
    """
    return {'status': 'ok', 'service': 'Ziv relay v1 (dev band + memory + schedule)', 'schedule': {'pending': scheduled.list_all(), 'loop_running': _schedule_task is not None and (not _schedule_task.done())}}

@app.post('/api/ziv/control/pause', dependencies=AUTHENTICATED)
async def control_pause() -> JSONResponse:
    """Suspend the always-on loop's next poll.

    Held as asset: the route is wired and the loop honours it, but the demo
    beat has not yet exercised it end to end through the device.
    """
    iface = _schedule_loop_iface
    if iface is None:
        raise HTTPException(status_code=503, detail='the always-on loop has not started yet')
    await iface.pause()
    return JSONResponse({'paused': True})

@app.post('/api/ziv/control/resume', dependencies=AUTHENTICATED)
async def control_resume() -> JSONResponse:
    """Let the always-on loop poll again.

    Held as asset: wired, not yet proven end to end.
    """
    iface = _schedule_loop_iface
    if iface is None:
        raise HTTPException(status_code=503, detail='the always-on loop has not started yet')
    await iface.resume()
    return JSONResponse({'resumed': True})

@app.post('/api/ziv/control/quit', dependencies=AUTHENTICATED)
async def control_quit() -> JSONResponse:
    """Ask the always-on loop to exit, and wait for it to have done so.

    Held as asset: wired, not yet proven end to end. The loop ends but the
    rest of the relay (HTTP, WS, the turn pump, the durable stores) keeps
    running — this is a loop stop, not a server stop.
    """
    iface = _schedule_loop_iface
    if iface is None:
        raise HTTPException(status_code=503, detail='the always-on loop has not started yet')
    await iface.quit()
    return JSONResponse({'loop_stopped': True, 'schedule_pending': scheduled.list_all()})

@app.get('/api/ziv/control', dependencies=AUTHENTICATED)
async def control_status() -> JSONResponse:
    """The control plane's own liveness readout.

    What a client can ask the control plane to do, and which of those
    capabilities are wired vs still held as asset.
    """
    iface = _schedule_loop_iface
    return JSONResponse({'loop': {'running': _schedule_task is not None and (not _schedule_task.done()), 'started': _schedule_loop_started, 'iface': iface is not None}, 'actions': {'pause': {'wired': iface is not None, 'held_as_asset': iface is None}, 'resume': {'wired': iface is not None, 'held_as_asset': iface is None}, 'quit': {'wired': iface is not None, 'held_as_asset': iface is None}}})
scheduled = ScheduledReminders()
_schedule_task: asyncio.Task[None] | None = None
_telemetry = TelemetryRing(maxlen=20, recent_tail=10)
memory = WearerMemory()
inbox = MessageInbox()

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

def haptic_frame(pattern_id: str, why: str='') -> dict[str, Any]:
    """One wearer-visible haptic event as a wire frame."""
    return {'type': 'haptic', 'pattern': pattern_id, 'ms': vibrate_pattern(pattern_id), 'why': why}

async def _announce_error(why: str) -> None:
    """The error long-buzz for a turn that dies before it starts.

    The spike's loud-not-silent rule: a failed transcription is not dead
    air — the wrist feels the long-buzz (an attention beat, the same class
    as the queue cue) and the wire log gets the words. No band attached:
    nothing to play on; the HTTP error still answers the sender.
    """
    try:
        await _push(haptic_frame(PATTERN_ERROR, why=why))
        await _push({'type': 'text', 'text': f'error: {why}'})
    except _NoDevices:
        pass

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
        raise _NoDevices('no dev band attached (open /ziv_client/index.html on the phone)')
    await hub.broadcast(frame)
gate = MessageGate()
_turn_lock = _LoopBoundLock()

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
            self.last_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            self._recent.append(time.monotonic())
            if len(self._recent) > self.WINDOW_MAX:
                self._recent.popleft()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cutoff = time.monotonic() - self.WINDOW_S
            while self._recent and self._recent[0] <= cutoff:
                self._recent.popleft()
            return {'count': self.count, 'per_minute': len(self._recent), 'window_s': self.WINDOW_S, 'last_reason': self.last_reason, 'last_at': self.last_at}

    def reset(self) -> None:
        with self._lock:
            self.count = 0
            self.last_reason = None
            self.last_at = None
            self._recent.clear()
queue_rejections = _RejectionStats()

def _omni_configured() -> bool:
    """Is an audio-capable Token Factory endpoint actually usable here?

    The same gate the client renders the Omni mic button against: a key alone
    is not enough, and a key one path has and the other does not must not
    leak between them. Empty/None is 'no'; any non-empty string is 'yes' 
    so the wiring is present — correctness of the real call is the server's
    problem, not the button's.
    """
    return bool(NEBIUS_API_KEY and ZIV_OMNI_MODEL)

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

async def _play_cells_and_close(text: str, *, note: str | None=None, free_fn=None) -> int:
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
    cells = [{'ch': ch, 'ms': timing.cell_ms(ch)} for ch in text.lower() if 'a' <= ch <= 'z'][:timing.SPELL_MAX_LETTERS]
    label = f'queued: {text}' if note else f'message: {text}'
    await _push({'type': 'text', 'text': label, 'chars': cells})
    gap = _effective_cell_gap_ms() / 1000.0
    for cell in cells:
        await _push({'type': 'cell', 'ch': cell['ch'], 'ms': cell['ms']})
        await _dwell(cell['ms'] / 1000.0 + gap)
    close = haptic_frame(PATTERN_END_OF_MESSAGE, why='close')
    if free_fn is not None and free_fn():
        close['free'] = True
    await _push(close)
    return len(cells)

async def _play_drained(drained: list[Any], owed: list[str]) -> None:
    """Replay the texts the gate drained as their own full events.

    The gate's queue is a *minutes*-long buffer, and every text in it has
    already cued on the wearer's wrist — so it must have exactly one drain
    point, and both owners of the channel come through here:

    * the turn pump, with the events ``TurnTimeline.finish_playback``
      drained at its close, and
    * inbox delivery, with whatever arrived while a stored backlog played.

    ``owed`` is the caller's "undelivered, oldest first" list. It is
    REPLACED with the drained texts and popped as each one's close plays,
    so a failure part-way through leaves exactly the unplayed remainder —
    which is what the caller's abort path hands to the inbox. The last
    replay's close carries the ``free`` marker (see
    ``_play_cells_and_close``): the wrist is only truly free after the last
    one, not after the turn's own.
    """
    owed[:] = [str(ev.payload.get('text', '')) for ev in drained]
    for idx in range(len(drained)):
        await _push(haptic_frame(PATTERN_MESSAGE_CUE, why='queued replay cue'))
        await _play_cells_and_close(owed[0], note=True, free_fn=lambda idx=idx, n=len(drained): idx == n - 1)
        owed.pop(0)

async def _transcribe_omni(audio_b64: str, mime: str) -> str:
    """One Token Factory Omni call: audio in, transcript text out.

    OpenAI-compatible chat completions with an ``input_audio`` content part:
    ``data`` is the **raw base64** audio and ``format`` names the container
    separately, which is the shape the OpenAI audio convention uses (a
    ``data:audio/...;base64,`` URL is Gemini's ``inlineData`` convention and
    does not belong in this field). Raises ``HTTPException(503)`` when no
    audio-capable endpoint is configured and ``HTTPException(502)`` with the
    provider's own words on any failure — the caller decides the
    wearer-visible path (the error long-buzz, never silence).
    """
    try:
        import httpx
    except ImportError as exc:
        raise HTTPException(status_code=500, detail='httpx unavailable') from exc
    payload = {'model': ZIV_OMNI_MODEL, 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': _OMNI_PROMPT}, {'type': 'input_audio', 'input_audio': {'data': audio_b64, 'format': mime}}]}], 'max_tokens': 512, 'temperature': 0.0}
    headers = {'Authorization': f'Bearer {NEBIUS_API_KEY}'}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(NEBIUS_BASE_URL.rstrip('/') + '/chat/completions', json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'Token Factory unreachable: {exc}') from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f'Token Factory error {resp.status_code}: {resp.text[:300]}')
    try:
        text = resp.json()['choices'][0]['message']['content']
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail='Token Factory reply had no transcript') from exc
    text = str(text).strip()
    if not text:
        raise HTTPException(status_code=502, detail='Omni heard nothing (empty transcript)')
    return text

async def compose_with_nebius(prompt: str, *, system: str='') -> str:
    """One Token Factory **text** call — the agent path.

    Same endpoint, same key, same OpenAI-compatible wire shape as the audio
    seam; a text body instead of an ``input_audio`` content part. This is the
    call the demo actually proves, so it gets the same loud-not-silent
    discipline: ``HTTPException(502)`` carrying the provider's words, never a
    silent empty string.
    """
    try:
        import httpx
    except ImportError as exc:
        raise HTTPException(status_code=500, detail='httpx unavailable') from exc
    payload = {'model': ZIV_TEXT_MODEL, 'messages': ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}], 'max_tokens': 64, 'temperature': 0.0}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(NEBIUS_BASE_URL.rstrip('/') + '/chat/completions', json=payload, headers={'Authorization': f'Bearer {NEBIUS_API_KEY}'})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'Token Factory unreachable: {exc}') from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f'Token Factory error {resp.status_code}: {resp.text[:300]}')
    try:
        out = str(resp.json()['choices'][0]['message']['content']).strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail='Token Factory reply had no text') from exc
    if not out:
        raise HTTPException(status_code=502, detail='model composed nothing')
    return out

def agent_path_available() -> bool:
    """Can the relay actually reach the model? Key present *and* a model id.

    Used to decide ``source`` before the call, so the wire log says
    ``text_live`` only when a real model call ran, and ``text_echo`` when the
    stored line is played verbatim instead. Never guesses.
    """
    return bool(NEBIUS_API_KEY and ZIV_TEXT_MODEL)

async def compose_reminder_line(intent: str) -> str:
    """Ask the model for the one line this reminder should play.

    The reminder the caller scheduled is an *intent* ("meds at nine"), not a
    finished sentence — turning it into the line a wrist reads is exactly the
    work an agent should do while nobody is chatting. The model's own words
    are what plays; nothing here invents or templates them.
    """
    line = await compose_with_nebius(f'Write the reminder line for this intent: {intent}', system=_COMPOSE_PROMPT)
    return line.strip().strip('"').splitlines()[0][:60] or intent

async def deliver_inbox_one() -> dict[str, Any] | None:
    """Deliver the oldest pending inbox message as its own full event.

    Marked delivered only *after* the close plays — a band vanishing
    mid-delivery leaves the message pending (redelivery, never loss).

    Delivery owns the haptic channel exactly the way a turn does
    (``gate.reserve()``): an inbox entry is already durable, so it must not
    interleave into a turn in flight, and — just as important — a *turn*
    must not interleave into the middle of a stored message. If the channel
    is already held the delivery declines and returns ``None``, leaving the
    entry pending for the next attach; nothing is lost, because nothing was
    touched. The turn lock additionally serializes two deliveries racing the
    same oldest entry, so the peek and the mark cannot straddle each other.

    After the entry's close it drains the gate queue: texts that arrived
    while a stored backlog played have already cued on the wrist, and this
    is the owner that owes them their content.

    Every replay is a self-naming turn: the entry's source picks the mark
    kind (a stored reminder replays with the reminder's triple-pulse tail,
    any other stored message with the message's double-tap), so the wrist
    feels who is calling — and what kind of event it was — before the
    stored content arrives.
    """
    async with _turn_lock:
        if not gate.reserve():
            return None
        owed: list[str] = []
        released = False
        try:
            entry = inbox.peek_one()
            if entry is None:
                released = True
                await _play_drained(gate.close_event(), owed)
                return None
            source = str(entry.get('source', 'message'))
            kind = 'reminder' if source == 'scheduled' else 'message'
            await _play_prefix_mark(kind, str(entry.get('text', '')))
            await _play_cells_and_close(str(entry.get('text', '')), note=True)
            owed = []
            inbox.mark_delivered(entry)
            released = True
            await _play_drained(gate.close_event(), owed)
        except BaseException:
            for stranded in owed if released else [*owed, *gate.abort()]:
                inbox.offer(stranded, source='queued')
            raise
    return entry

async def run_message_turn(text: str, *, source: str='message', prefix_mark: str | None=None) -> dict[str, Any]:
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

    A turn that dies part-way through (the band vanishing mid-content, or a
    cancellation) releases the gate and hands every undelivered text to the
    inbox before re-raising: the channel is freed for the next arrival and
    nothing the wearer never felt is lost. Redelivery, never a silent drop.
    """
    if hub.count == 0:
        entry = inbox.offer(text, source=source)
        return {'event': 'inbox:stored', 'stored': True, 'inbox_pending': inbox.count(), 'at': entry['at']}
    decision = gate.admit(text)
    if decision.event_type == 'message:rejected':
        queue_rejections.record(str(decision.payload.get('reason', 'queue_full')))
        cap = int(decision.payload.get('cap', MessageGate.MAX_QUEUED))
        raise HTTPException(status_code=429, detail=f'message rejected: the replay queue is full ({cap} queued) — the wearer releases it after the current turn; try again later')
    if decision.event_type != 'message:play':
        await _push(haptic_frame(PATTERN_MESSAGE_CUE, why='queued'))
        return {'event': decision.event_type, 'queued': True, 'queue_len': len(gate)}
    owed: list[str] = [text]
    turn: TurnTimeline | None = None
    released = False
    try:
        async with _turn_lock:
            if prefix_mark is not None:
                await _play_prefix_mark(prefix_mark, text)
            turn = TurnTimeline(gate, text=text)

            def frame_for(ev: Any) -> dict[str, Any]:
                et = ev.event_type
                if et == 'message:play':
                    return haptic_frame(PATTERN_MESSAGE_CUE, why='kind cue')
                if et == f'attention:{PATTERN_PROCESSING}':
                    return haptic_frame(PATTERN_PROCESSING, why='working')
                if et == f'attention:{PATTERN_ERROR}':
                    return haptic_frame(PATTERN_ERROR, why='error')
                if et == 'lifecycle:playback_done':
                    return haptic_frame(PATTERN_END_OF_MESSAGE, why='close')
                return {'type': 'text', 'text': et}
            t0 = time.monotonic()
            await _push(frame_for(turn.events[0]))
            if decision.event_type == 'message:play':
                gate.reserve()
            turn.begin_processing(now_s=0.0)
            await _push(frame_for(turn.events[-1]))
            tick = 0.05
            waited = 0.0
            while waited < FAKE_MODEL_SECONDS:
                await _dwell(tick)
                waited += tick
                ev = turn.poll(now_s=waited)
                if ev is not None:
                    await _push(frame_for(ev))
            turn.begin_playback()
            await _push(frame_for(turn.events[-1]))
            await _play_cells_and_close(text, free_fn=lambda: len(gate) == 0)
            owed.pop(0)
            replay = turn.finish_playback(now_s=round(time.monotonic() - t0, 1))
            drained = replay[1:]
            released = True
            await _play_drained(drained, owed)
            _telemetry.record(label='message_turn', seconds=turn.seconds, retries=turn.retries, source=source, queued=len(drained))
            return {'event': 'turn_complete', 'seconds': turn.seconds, 'events': [ev.event_type for ev in turn.events], 'drained': len(drained)}
    except BaseException as exc:
        if not released:
            owed.extend(gate.abort())
        for pending_text in owed:
            inbox.offer(pending_text, source=source)
        _telemetry.record(label='message_turn_aborted', seconds=0.0, retries=turn.retries if turn is not None else 0, source=source, reason=type(exc).__name__, stranded=len(owed))
        LOGGER.warning('turn_aborted source=%s reason=%s stranded=%d — gate released, undelivered texts stored in the inbox', source, type(exc).__name__, len(owed))
        raise

@app.websocket('/ws')
async def ws_device(ws: WebSocket, token: str | None=Query(default=None)) -> None:
    """The device transport: attach, greet, drain, detach.

    Held-as-asset additions (announced in the narrative, not yet proven end
    to end on the real device):

    * The hello ack now carries the control plane's liveness so the phone can
      show whether the always-on loop is running without a separate HTTP call.
    * A heartbeat every ``WS_HEARTBEAT_S`` keeps the connection's liveness
      visible to the phone and lets it tell a dead relay from a silent room.
    * Client frames are still drained but not yet interpreted — ``pause``
      arrives as a client-initiated WS message in the next build step, not as
      an HTTP route the phone polls. ``control_pause`` above is the server's
      own endpoint; the phone calls it when it can, and the WS channel is the
      path reserved for it.
    """
    global _schedule_loop_iface
    if not _authorized_websocket(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    await hub.attach(ws)
    try:
        pending = inbox.count()
        control_state = {'loop_running': _schedule_task is not None and (not _schedule_task.done()), 'loop_started': _schedule_loop_started, 'iface': _schedule_loop_iface is not None}
        await ws.send_text(json.dumps({'type': 'hello', 'spec_version': timing.SPEC_VERSION, 'patterns': list(timing.PATTERN_IDS), 'mark': timing.PREFIX_MARK, 'inbox_pending': pending, 'control': control_state}, ensure_ascii=False))
        if pending:
            try:
                while await deliver_inbox_one() is not None:
                    pass
            except _NoDevices:
                pass
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=WS_HEARTBEAT_S)
            except asyncio.TimeoutError:
                await _push({'type': 'heartbeat', 'control': control_state})
            except _NoDevices:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        hub.detach(ws)

@app.post('/api/ziv/message')
async def post_message(body: dict[str, Any], authorization: str | None=Header(default=None)) -> JSONResponse:
    """One inbound message → gate → timeline → WS frames → the wrist."""
    _authorized_http(authorization)
    text = str(body.get('text', '')).strip()
    if not text:
        raise HTTPException(status_code=422, detail='text is required')
    try:
        result = await run_message_turn(text, source='message')
    except _NoDevices as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(result)

@app.post('/inject/audio')
async def inject_audio(body: dict[str, Any], authorization: str | None=Header(default=None)) -> JSONResponse:
    """The Omni spike's seam (week 1), now real: mic audio → transcript → turn.

    The PWA records the mic (MediaRecorder) and posts
    ``{"audio_b64": "…", "mime": "webm", "lang": "en"}``. Without an
    audio-capable endpoint configured this answers 503 — a refusal, never a
    silent failure. ``{"simulate": "<text>"}`` is the keyless path the demo
    runs; it takes the *same turn* a typed message would, so cues, ticks,
    cells, close and the queue are all exercised either way.
    """
    _authorized_http(authorization)
    simulate = str(body.get('simulate') or '').strip()
    audio_b64 = str(body.get('audio_b64') or '').strip()
    if not simulate and (not audio_b64):
        raise HTTPException(status_code=422, detail="provide 'audio_b64' (+ 'mime': webm|ogg|mp4|mp3|wav) or 'simulate' (keyless stub)")
    if simulate:
        text, source = (simulate, 'audio_stub')
    else:
        if not NEBIUS_API_KEY:
            raise HTTPException(status_code=503, detail='NEBIUS_API_KEY is not set — transcription unavailable; use {"simulate": "…"} for the keyless path')
        if not ZIV_OMNI_MODEL:
            raise HTTPException(status_code=503, detail='no audio-capable endpoint configured — set ZIV_OMNI_MODEL to an endpoint that accepts audio input; use {"simulate": "…"} for the keyless path')
        mime = str(body.get('mime') or 'webm').strip().lower()
        allowed = {'webm', 'ogg', 'mp4', 'mp3', 'wav'}
        if mime not in allowed:
            raise HTTPException(status_code=422, detail=f'unsupported mime {mime!r} — one of {sorted(allowed)}')
        try:
            text = await _transcribe_omni(audio_b64, mime)
        except HTTPException as exc:
            await _announce_error(f'transcription failed ({exc.status_code})')
            raise
        source = 'audio_omni'
    try:
        result = await run_message_turn(text, source=source)
    except _NoDevices as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({'source': source, **result})

@app.get('/api/ziv/inbox', dependencies=AUTHENTICATED)
def get_inbox() -> dict[str, Any]:
    """The wearer's inbox: pending messages, oldest first (the wrist shows
    them as pending until the wearer's band takes them)."""
    return {'pending': inbox.pending(), 'count': inbox.count(), 'cap': INBOX_CAP}

@app.delete('/api/ziv/inbox', dependencies=AUTHENTICATED)
def clear_inbox() -> dict[str, Any]:
    """The wearer discards everything pending — the inbox answers to them."""
    return {'cleared': inbox.clear()}

@app.get('/api/ziv/prefs', dependencies=AUTHENTICATED)
def get_prefs() -> dict[str, Any]:
    """The wearer's playback-pace preference, clamped into the spec envelope."""
    return {'cell_gap_ms': _effective_cell_gap_ms(), 'cell_gap_min_ms': timing.CELL_GAP_MIN_MS, 'cell_gap_max_ms': timing.CELL_GAP_MAX_MS, 'cell_gap_default_ms': timing.CELL_GAP_DEFAULT_MS}

@app.post('/api/ziv/prefs', dependencies=AUTHENTICATED)
def set_prefs(body: dict[str, Any]) -> dict[str, Any]:
    """Store the playback-pace preference (parameters are personal; the
    envelope is the spec's — values outside it are clamped, not rejected)."""
    if 'cell_gap_ms' not in body:
        raise HTTPException(status_code=422, detail='cell_gap_ms is required')
    memory.set(WearerMemory.PREF_CELL_GAP, body['cell_gap_ms'])
    return get_prefs()

@app.get('/api/ziv/timing')
def get_timing() -> dict[str, Any]:
    """The generated timing module, serialized — the client's beat source.

    The phone bootstraps its vibrate patterns from the same derivation the
    firmware header was generated from (plan §4: structure is universal).
    The drift guard holds this module against the spec; the client adds no
    numbers of its own.
    """
    return {'spec_version': timing.SPEC_VERSION, 'patterns': {pid: list(timing.pattern_beats(pid)) for pid in timing.PATTERN_IDS}, 'letters': {ch: timing.cell_ms(ch) for ch in timing.LETTERS}, 'letter_masks': dict(timing.LETTER_MASKS), 'mark': timing.PREFIX_MARK, 'mark_cells': list(timing.MARK_CELLS[timing.PREFIX_MARK]), 'prefix_tails': dict(timing.PREFIX_TAILS), 'prefix_breath_ms': timing.PREFIX_BREATH_MS, 'cell_gap_ms': timing.CELL_GAP_DEFAULT_MS, 'spell_max_letters': timing.SPELL_MAX_LETTERS}

@app.get('/api/ziv/health')
def health() -> dict[str, Any]:
    """Operator view — deliberately public, and deliberately content-free.

    The PWA's queue badge polls this before it has any credential, so it is
    not bearer-gated. It answers counts, caps, model wiring, turn telemetry and corrupt-store flags — never a message's text, a reminder's line, or a preference value. Anything added here must keep that property; the routes that DO carry content are the ``AUTHENTICATED`` ones.
    """
    schedule_pending = scheduled.count()
    inbox_pending = inbox.count()
    prefs = {'cell_gap_ms': _effective_cell_gap_ms()}
    corrupt = memory.take_corrupt_files() + inbox.take_corrupt_files() + scheduled.take_corrupt_files()
    return {'status': 'ok', 'service': 'Ziv relay v1 (dev band + memory)', 'devices': hub.count, 'spec_version': timing.SPEC_VERSION, 'fake_model_seconds': FAKE_MODEL_SECONDS, 'auth': bool(ZIV_RELAY_TOKEN), 'text': {'key_set': bool(NEBIUS_API_KEY), 'base_url': NEBIUS_BASE_URL.rstrip('/'), 'model': ZIV_TEXT_MODEL, 'available': agent_path_available()}, 'omni': {'key_set': _omni_configured(), 'model': ZIV_OMNI_MODEL, 'configured': bool(ZIV_OMNI_MODEL)}, 'queue_rejections': queue_rejections.snapshot(), 'gate_queue': len(gate), 'gate_queue_cap': MessageGate.MAX_QUEUED, 'inbox_pending': inbox_pending, 'inbox_cap': INBOX_CAP, 'inbox_evicted': inbox.evictions(), 'schedule_pending': schedule_pending, 'schedule_cap': SCHEDULE_CAP, 'schedule_evicted': scheduled.evictions(), 'schedule_corrupt': 'schedule' in corrupt, 'prefs': prefs, 'store_problems': corrupt, 'turns': _telemetry.stats(), 'schedule_loop': {'running': _schedule_task is not None and (not _schedule_task.done()), 'poll_s': 1.0, 'last_fire_at': _telemetry.last('scheduled_reminder_fired')}}


@app.get('/')
@app.get('/favicon.ico')
def ziv_root() -> RedirectResponse:
    """The bare host lands on the phone client — a shared link should just work."""
    return RedirectResponse(url='/ziv_client/index.html', status_code=307)


@app.get('/ziv_client')
@app.get('/ziv_client/')
def ziv_client_root() -> RedirectResponse:
    """A bare /ziv_client (what a person types) lands on the client page."""
    return RedirectResponse(url='/ziv_client/index.html', status_code=307)


@app.get('/ziv_client/manifest.json', response_class=Response)
def ziv_client_manifest(request: Request) -> Response:
    return Response(content=_static_path('ziv_manifest.json').read_bytes(), media_type='application/json', headers={'Cache-Control': 'public, max-age=86400, immutable'})


@app.get('/ziv_client/index.html', response_class=Response)
def ziv_client_index(request: Request) -> Response:
    return Response(content=_static_path('index.html').read_bytes(), media_type='text/html', headers={'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*'})


@app.get('/ziv_client/ziv_icon.png', response_class=Response)
def ziv_client_icon_png(request: Request) -> Response:
    return Response(content=_static_path('ziv_icon.png').read_bytes(), media_type='image/png', headers={'Cache-Control': 'public, max-age=86400, immutable'})


@app.get('/ziv_client/ziv_icon.svg', response_class=Response)
def ziv_client_icon_svg(request: Request) -> Response:
    return Response(content=_static_path('ziv_icon.svg').read_bytes(), media_type='image/svg+xml', headers={'Cache-Control': 'public, max-age=86400, immutable'})


@app.get('/ziv_client/ziv_sw.js', response_class=Response)
def ziv_client_sw(request: Request) -> Response:
    return Response(content=_static_path('ziv_sw.js').read_bytes(), media_type='application/javascript', headers={'Cache-Control': 'public, max-age=86400, immutable'})


ZIV_CLIENT_PATH_ROUTES = ('/ziv_client/static/{path:path}', '/ziv_client/manifest.json', '/ziv_client/ziv_icon.png', '/ziv_client/ziv_sw.js', '/ziv_client/index.html')

INDEX_FILE = (Path(__file__).resolve().parent / 'ziv_client' / 'index.html').resolve()
ZIV_CLIENT_DIR = INDEX_FILE.parent
ZIV_CLIENT_DIR_FOR_RESOLVE = (Path(__file__).resolve().parent / 'ziv_client').resolve()

_STATICS = {}

def _static_path(path: str) -> Path:
    normalized = os.path.normpath(path).lstrip(os.sep)
    if os.path.isabs(normalized) or normalized.startswith('..') or chr(0) in normalized:
        raise HTTPException(status_code=400, detail='bad client path')
    p = (ZIV_CLIENT_DIR_FOR_RESOLVE / normalized).resolve()
    try:
        p.relative_to(ZIV_CLIENT_DIR_FOR_RESOLVE)
    except ValueError:
        raise HTTPException(status_code=404, detail='client asset missing')
    if not p.is_file():
        raise HTTPException(status_code=404, detail='client asset missing')
    return p


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=ZIV_PORT)
