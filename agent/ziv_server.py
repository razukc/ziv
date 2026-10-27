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
  log. ``?session=<id>`` joins that band's private stream: each id gets its
  own hub, gate and turn lock, so two open clients never share turns. No id
  joins ``default`` (the original single-band behaviour).
* ``POST /api/ziv/message`` — one inbound message through the real seam:
  the target session's ``MessageGate`` decides play-now vs cue-and-queue
  (invariant 4 — a message arriving mid-turn queues, it never barges) and
  ``message:play`` **reserves the channel for the whole turn**, model wait
  and all, so the queue-don't-interrupt policy covers the quiet stretches
  too. An arrival when the replay queue is full (``MessageGate.MAX_QUEUED``)
  is rejected with 429 — bounded memory; the sender is told no, loudly.
  The body's ``session`` picks the stream; only that session's devices see
  the turn. ``TurnTimeline`` emits the journey (cue → ``processing`` → playing →
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
import re
import sys
import threading
import time
import weakref
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
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

    The reminder is wearer-level, so it goes to ONE session: the band in use
    (``SessionRegistry.active`` — the legacy default when an unnamed client
    is attached, else the newest band). Playing it on every open client would
    be the duplicate delivery sessions exist to stop.
    """
    fired: list[dict[str, Any]] = []
    for r in scheduled.take_due():
        try:
            text, source = (r['text'], r['source'])
            if source == 'agent':
                if agent_path_configured():
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
                    compose_health.record(
                        ok=False, error='no_key',
                        detail='NEBIUS_API_KEY is not set; the intent played verbatim.',
                    )
            await run_message_turn(
                text, source=source, prefix_mark='reminder',
                session=sessions.active(),
            )
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
# The band spells SPELL_MAX_LETTERS cells and nothing else, so the cap has to
# live in the prompt *and* be measured on the reply: a thirteen-letter line is
# sliced at twelve by `_play_cells_and_close`, which loses its last letter at
# the far end of the turn where the wearer — not the caller — finds out.
_COMPOSE_LETTERS = timing.SPELL_MAX_LETTERS
_COMPOSE_PROMPT = (
    'You compress one reminder into the single line a vibro-braille band plays to a '
    'deafblind wearer. '
    f'The band has {_COMPOSE_LETTERS} cells; spaces and punctuation take none, so the whole '
    f'line must be {_COMPOSE_LETTERS} letters at most. Reply with 2 or 3 short words and '
    'nothing else. If the line you want is too long, drop whole words until what is left '
    'fits: 16 letters of "remember to buy milk" become the 7 letters of "buy milk". '
    'Write numbers as words. Reply only with the line.'
)
# The worked example shows the *operation*, not an answer: a concrete reminder in
# the system prompt gets copied verbatim for unrelated intents (a live take turned
# "meds at 9" into "pills at nine" when the example mentioned pills).
_CORRECTION_PROMPT = (
    'That line cannot play whole: {problem}. Cut it to 2 or 3 words, {cap} letters or '
    'fewer, dropping words — not letters, not spaces. Write numbers as words. '
    'Intent: {intent}'
)
_SHORTEST_PROMPT = 'Reply with only the two most useful words, nothing else. Intent: {intent}'


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

@app.get('/api/ziv/model/check', dependencies=AUTHENTICATED)
async def model_check() -> JSONResponse:
    """Ask the provider, right now, whether the configured model answers.

    200: the model replied (``sample`` shows what it said).
    502: the provider answered with an error, or was unreachable; ``detail``
         carries its own words with the key redacted.
    503: nothing to test — no key, no model id, or httpx missing.

    One small call per request. It is not part of ``/health`` because a
    health poll must not spend credit, and because the point is an explicit
    operator check, not a number that silently ages.
    """
    report = await probe_text_model()
    return JSONResponse(report, status_code=int(report['http_status']))


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

async def _announce_error(why: str, *, session: RelaySession | None = None) -> None:
    """The error long-buzz for a turn that dies before it starts.

    The spike's loud-not-silent rule: a failed transcription is not dead
    air — the wrist feels the long-buzz (an attention beat, the same class
    as the queue cue) and the wire log gets the words. No band attached:
    nothing to play on; the HTTP error still answers the sender.
    """
    target = session or _current_session()
    if target.hub.count == 0:
        return
    await target.hub.broadcast(haptic_frame(PATTERN_ERROR, why=why))
    await target.hub.broadcast({'type': 'text', 'text': f'error: {why}'})
    target.note_frame('haptic')

@dataclass
class DeviceHub:
    """The devices attached to one session, and the send discipline.

    One wrist, one playback loop. Frames fan out to every device attached to
    *this* session — the same browser/session opened twice is still one band —
    but never to another session's devices. Haptic frames are fire-and-forget
    by design: haptics are not request/response, and one slow or dead client
    must never stall the turn pump.
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
gate = MessageGate()
_turn_lock = _LoopBoundLock()

class RelaySession:
    """One band's private playback stream: hub, gate and turn lock.

    The relay used to keep one process-wide hub and gate, which meant every
    open client felt every message: two phones, two browsers, one wrist. A
    session gives each connected band its own attached devices, its own
    queue-don't-interrupt gate and its own turn lock, so a message posted for
    session A plays on A's wires only. The timing spec, the wearer's inbox,
    preferences and the reminder schedule stay wearer-level (see the module
    docstring) — only *playback* is per session.

    The ``default`` session is the compatibility seam: it delegates to the
    module-level ``hub`` / ``gate`` / ``_turn_lock``, so drivers written
    before sessions (the hermetic suite, curl, the demo scripts) keep working
    unchanged and a request with no session id lands there.
    """

    def __init__(self, session_id: str, *, hub: 'DeviceHub | None' = None,
                 gate: 'MessageGate | None' = None,
                 lock: '_LoopBoundLock | None' = None) -> None:
        self.session_id = session_id
        self._hub = hub if hub is not None else DeviceHub()
        self._gate = gate if gate is not None else MessageGate()
        self.lock = lock if lock is not None else _LoopBoundLock()
        self.attached_at = time.monotonic()
        self.last_frame_mono: float | None = None

    @property
    def hub(self) -> 'DeviceHub':
        return self._hub

    @property
    def gate(self) -> 'MessageGate':
        return self._gate

    def note_frame(self, frame_type: str | None) -> None:
        """Stamp the last wearer-visible frame pushed to this band.

        Heartbeats are transport liveness, not content: counting them would
        make every attached band look active forever. The badge popover uses
        this stamp to show when the band last actually felt something.
        """
        if frame_type == 'heartbeat':
            return
        self.last_frame_mono = time.monotonic()

    def idle(self) -> bool:
        """Nothing attached and nothing in flight — safe to forget."""
        return self.hub.count == 0 and not self.gate.playing and len(self.gate) == 0

class _DefaultSession(RelaySession):
    """The unnamed session: the module-level hub, gate and turn lock.

    Reading ``hub``/``gate`` through properties (not copies) is deliberate:
    the test fixture replaces ``zs.gate`` between cases and clears
    ``zs.hub.devices``, and a turn with no session id must see exactly that
    state.
    """

    def __init__(self) -> None:
        super().__init__('default', hub=hub, gate=gate, lock=_turn_lock)

    @property
    def hub(self) -> 'DeviceHub':
        return hub

    @property
    def gate(self) -> 'MessageGate':
        return gate

class SessionIdError(ValueError):
    """A session id the relay will not create (unbounded or unsafe input)."""

class SessionLimit(RuntimeError):
    """Too many live sessions; the caller has to wait for one to go idle."""

_SESSION_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$')

def _clean_session_id(raw: Any) -> str:
    """Normalize a requested session id; empty means the default session.

    Client-generated ids are UUIDs, but the id is caller input: it is bounded
    to 64 characters and a safe alphabet so it can be logged and shown without
    becoming a memory/identity hole.
    """
    sid = str(raw or '').strip()
    if not sid:
        return 'default'
    if not _SESSION_ID_RE.match(sid):
        raise SessionIdError(
            'session must be 1-64 characters of letters, digits, dot, colon, '
            'underscore or dash'
        )
    return sid

class SessionRegistry:
    """The live sessions, bounded and reclaimable.

    A session is forgotten when its last device detaches and its gate is idle.
    Creating a new one first drops every idle session, so a tab that closes
    without a clean detach cannot accumulate forever; the hard cap is the
    backstop for a flood of genuinely live sessions.
    """

    MAX_SESSIONS = 32

    def __init__(self, default: RelaySession) -> None:
        self._sessions: dict[str, RelaySession] = {default.session_id: default}
        self._lock = threading.Lock()
        self.default = default

    @staticmethod
    def _reap_locked(store: dict[str, RelaySession]) -> None:
        for sid, session in list(store.items()):
            if sid != 'default' and session.idle():
                del store[sid]

    def get(self, raw: Any = None, *, create: bool = True) -> RelaySession:
        sid = _clean_session_id(raw)
        with self._lock:
            session = self._sessions.get(sid)
            if session is not None or not create:
                return session  # type: ignore[return-value]
            if sid != 'default':
                self._reap_locked(self._sessions)
                if len(self._sessions) >= self.MAX_SESSIONS:
                    raise SessionLimit(
                        f'{self.MAX_SESSIONS} live sessions — close an idle band first'
                    )
            session = RelaySession(sid)
            self._sessions[sid] = session
            return session

    def touch(self, session: RelaySession) -> None:
        """Mark a session as the most recently attached band."""
        session.attached_at = time.monotonic()

    def release(self, session: RelaySession) -> None:
        """Forget a session once it is genuinely idle (never the default)."""
        if session.session_id == 'default':
            return
        with self._lock:
            if self._sessions.get(session.session_id) is session and session.idle():
                del self._sessions[session.session_id]

    def active(self) -> RelaySession:
        """The band an unnamed POST or unsolicited turn should use.

        Three cases, in order:

        1. A legacy client (one that connected without a session id) is
           attached: it is the ``default`` band, and unnamed traffic is what
           it has always received.
        2. Otherwise the most recently attached session. A sender that does
           not know a tab's id (curl, the demo scripts, a webhook, the
           scheduler) is addressing the wearer, not a particular window —
           playing on every open tab would be exactly the duplicate delivery
           sessions exist to stop.
        3. Nothing attached: ``default``, whose caller stores the message in
           the wearer's inbox.
        """
        with self._lock:
            default = self._sessions.get('default')
            if default is not None and default.hub.count:
                return default
            attached = [s for s in self._sessions.values() if s.hub.count]
        if not attached:
            return self.default
        return max(attached, key=lambda s: s.attached_at)

    def total_devices(self) -> int:
        with self._lock:
            return sum(s.hub.count for s in self._sessions.values())

    def total_queued(self) -> int:
        with self._lock:
            return sum(len(s.gate) for s in self._sessions.values())

    def describe(self) -> list[dict[str, Any]]:
        """Content-free session view for health.

        Ids, device count, queue depth, playing state and the age of the last
        wearer-visible frame. Not named ``snapshot``: that name belongs to the
        health payload's rejection stats, and a second one earlier in the file
        would shadow it for the source-level badge contract.
        """
        now = time.monotonic()
        with self._lock:
            rows = sorted(self._sessions.values(), key=lambda s: s.attached_at, reverse=True)
        return [
            {'id': s.session_id, 'devices': s.hub.count,
             'queue': len(s.gate), 'playing': s.gate.playing,
             'last_frame_age_s': (round(now - s.last_frame_mono, 1)
                                  if s.last_frame_mono is not None else None)}
            for s in rows
        ]

sessions = SessionRegistry(_DefaultSession())
_inbox_lock = _LoopBoundLock()

_SESSION_CTX: ContextVar[RelaySession | None] = ContextVar('ziv_session', default=None)

def _current_session() -> RelaySession:
    """The session this task's turn belongs to (default when unset).

    A ContextVar, not an argument threaded through every helper: frame
    pushing, prefix marks, drains and closes all read the same session, and
    concurrent requests for different sessions each run in their own task
    with their own context.
    """
    return _SESSION_CTX.get() or sessions.default

class _NoDevices(RuntimeError):
    pass

async def _push(frame: dict[str, Any]) -> None:
    session = _current_session()
    if session.hub.count == 0:
        raise _NoDevices(
            f'no dev band attached to session {session.session_id!r} '
            '(open /ziv_client/index.html on the phone)'
        )
    await session.hub.broadcast(frame)
    session.note_frame(frame.get('type'))

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

def _spelled(text: str) -> str:
    """Exactly the letters the band spells for ``text`` — one cell each.

    Spaces, punctuation and digits take no cells. This is both the cap measure
    (``len(_spelled(line))``) and the cell sequence, deliberately the same
    function for both: the check that a composed line fits cannot drift from
    the slice that plays it.
    """
    return ''.join(ch for ch in str(text).lower() if 'a' <= ch <= 'z')


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
    cells = [{'ch': ch, 'ms': timing.cell_ms(ch)} for ch in _spelled(text)][:timing.SPELL_MAX_LETTERS]
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

async def compose_with_nebius(prompt: str, *, system: str='',
                              api_key: str | None = None) -> str:
    """One Token Factory **text** call — the agent path.

    Same endpoint, same OpenAI-compatible wire shape as the audio seam; a text
    body instead of an ``input_audio`` content part. This is the call the demo
    actually proves, so it gets the same loud-not-silent discipline:
    ``HTTPException(502)`` carrying the provider's words, never a silent empty
    string.

    ``api_key`` overrides the relay's own key for exactly this call. It is the
    one-shot judge path: passed in, used once, never assigned to a module
    global and never stored. Unset means the configured ``NEBIUS_API_KEY``.
    """
    key = api_key or NEBIUS_API_KEY
    try:
        import httpx
    except ImportError as exc:
        raise HTTPException(status_code=500, detail='httpx unavailable') from exc
    # Nemotron 3 is a reasoning model. Without this switch it spends the
    # whole 64-token budget inside ``reasoning`` and returns content: null;
    # the provider honours the vLLM switch, and the null guard below still
    # refuses loudly if a model ignores it.
    payload = {'model': ZIV_TEXT_MODEL, 'messages': ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}], 'max_tokens': 64, 'temperature': 0.0, 'chat_template_kwargs': {'enable_thinking': False}}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(NEBIUS_BASE_URL.rstrip('/') + '/chat/completions', json=payload, headers={'Authorization': f'Bearer {key}'})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'Token Factory unreachable: {exc}') from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f'Token Factory error {resp.status_code}: {resp.text[:300]}')
    try:
        content = resp.json()['choices'][0]['message']['content']
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail='Token Factory reply had no text') from exc
    if content is None:
        # A reasoning model that spends its whole budget before writing the
        # answer returns 200 with content: null. ``str(None)`` would play the
        # word "None" on the band, so this is a loud provider failure instead.
        raise HTTPException(
            status_code=502,
            detail='Token Factory answered 200 with content: null — the model produced reasoning only, not a line',
        )
    out = str(content).strip()
    if not out:
        raise HTTPException(status_code=502, detail='model composed nothing')
    return out


def _band_line(raw: str) -> str:
    """The model's reply as the one line that would play: cleaned, never cut.

    No character limit here on purpose — truncating a reply is the defect this
    path exists to prevent; the cap is enforced by re-asking, not by slicing.
    """
    lines = [ln.strip() for ln in str(raw).strip().splitlines() if ln.strip()]
    return (lines[0] if lines else '').strip('"').strip("'").strip()


_NUMBER_WORDS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five',
    '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine', '10': 'ten',
    '11': 'eleven', '12': 'twelve',
}


def _spoken_numbers(text: str) -> str:
    """Digits as words — the rule the console already states ("digits are spoken out").

    The band has no cell for a digit, so ``meds at 9`` would play ``meds at`` and
    lose the time; the model keeps writing the digit however firmly it is asked
    (a live run failed all three rungs on ``meds at 9``). This spells the number
    the model wrote — it never chooses or changes one — and leaves anything
    outside the table (``13``, ``9:30``) to the retry, which can rephrase.
    """
    def spell(match: re.Match) -> str:
        word = _NUMBER_WORDS.get(match.group())
        if word is None:
            return match.group()
        # "9am" reads as "nine am", not "nineam".
        glued = match.end() < len(text) and text[match.end()].isalpha()
        return word + (' ' if glued else '')

    return re.sub(r'\d+', spell, text)


def _band_problem(line: str) -> str | None:
    """Why ``line`` cannot play whole, in the model's own terms, or ``None``.

    Three ways a composed line loses content on the wrist, measured by the same
    ``_spelled`` the player uses: nothing spellable at all, a digit that no
    cell carries (``_spoken_numbers`` spells the common ones first), or more
    letters than there are cells. The sentence is reused as the retry's reason,
    so the correction names the real defect instead of just "shorter".
    """
    if not _spelled(line):
        return 'no letter in it can be felt'
    if any(ch.isdigit() for ch in line):
        return 'a digit is never felt (the band spells letters only)'
    letters = len(_spelled(line))
    if letters > _COMPOSE_LETTERS:
        return f'{letters} letters, and the band has room for {_COMPOSE_LETTERS}'
    return None


async def compose_band_line(intent: str, *, api_key: str | None=None) -> str:
    """The reminder line, guaranteed to fit the band's spell cap in full.

    ``intent`` is what the caller promised; the model writes what plays. The
    reply is measured with the same ``_spelled`` the cell player slices with,
    so "fits" means "no cell is dropped":

    * playable whole — returned as written (digits spelled out, since the band
      has no cell for one and a dropped "9" loses the time);
    * not playable — one corrective call that names the defect (a
      thirteen-letter answer for twelve cells was the take that exposed this);
    * still not playable — one last rung asking for two words, then a loud 502
      carrying counts only, never the line.
      The scheduled path turns that into ``text_echo`` of the intent, so the
      promise still fires and the log names the path it took.

    ``api_key`` is the one-shot judge credential, used for every attempt and
    never stored.
    """
    cap = _COMPOSE_LETTERS

    async def ask(prompt: str) -> str:
        return _spoken_numbers(_band_line(await compose_with_nebius(
            prompt, system=_COMPOSE_PROMPT, api_key=api_key,
        )))

    line = await ask(f'Write the reminder line for this intent: {intent}')
    problem = _band_problem(line)
    if problem is None:
        return line
    line = await ask(_CORRECTION_PROMPT.format(problem=problem, cap=cap, intent=intent))
    problem = _band_problem(line)
    if problem is None:
        return line
    # The last rung asks for a word *count* rather than a letter count: this
    # model follows "two words" far more reliably than "twelve letters", and
    # two short words almost always fit. Measured live at 10/10 intents.
    line = await ask(_SHORTEST_PROMPT.format(intent=intent))
    problem = _band_problem(line)
    if problem is None:
        return line
    raise HTTPException(
        status_code=502,
        detail=(f'model answered a line the band cannot spell in full after 3 tries: '
                f'{problem} — refusing to play a line with its tail cut off'),
    )

def agent_path_configured() -> bool:
    """Can a live call be ATTEMPTED? Key present *and* a model id.

    This is a wiring check, not a success claim: a present-but-unfunded key is
    configured and still fails every call. Used to decide ``source`` before the
    call, so the wire log says ``text_live`` only when a real model call ran,
    and ``text_echo`` when the stored line is played verbatim instead.
    """
    return bool(NEBIUS_API_KEY and ZIV_TEXT_MODEL)


def agent_path_available() -> bool | None:
    """Did the model path actually work? ``None`` until a real compose is tried.

    Read from the last compose record, not from the key. Health used to answer
    this with ``agent_path_configured()`` — so a relay whose key had no credit
    still reported ``available: true`` and today's failure was invisible.
    """
    return compose_health.last_ok()


def _redact(text: str, secret: str = '') -> str:
    """Provider words are useful in a diagnostic; the credential is not.

    Both the configured key and an explicitly supplied one are scrubbed, so a
    provider that echoes part of an Authorization header cannot turn a
    diagnostic response into a credential leak.
    """
    for value in (secret, NEBIUS_API_KEY):
        if value and value in text:
            text = text.replace(value, '[redacted]')
    return text


def _compose_error_kind(detail: str) -> str:
    """Name the failure from the words ``compose_with_nebius`` raises."""
    if detail.startswith('Token Factory unreachable'):
        return 'unreachable'
    if detail.startswith('Token Factory error'):
        return 'provider_error'
    if detail.startswith('model answered'):
        return 'too_long'
    return 'bad_reply'


class ComposeHealth:
    """What happened on the last model compose — never what was composed.

    ``text.configured`` in health answers only "is a key wired up?"; it cannot
    tell an operator whether the provider accepts that key. This is the other
    half: status, provider words and time of the last real attempt, with no
    intent and no composed line — and ``text.available`` reads this record, so
    the flag can only be true after a call that actually worked. One assignment
    per record, so a reader never sees a half-written entry.
    """

    def __init__(self) -> None:
        self._last: dict[str, Any] | None = None

    def record(self, *, ok: bool, status: int | None = None,
               error: str | None = None, detail: str | None = None,
               secret: str = '') -> None:
        self._last = {
            'ok': ok,
            'status': status,
            'error': error,
            'detail': _redact(detail, secret)[:300] if detail else None,
            'model': ZIV_TEXT_MODEL,
            'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }

    def snapshot(self) -> dict[str, Any] | None:
        return dict(self._last) if self._last else None

    def last_ok(self) -> bool | None:
        """The last attempt's outcome, or ``None`` if none has been made."""
        return None if self._last is None else bool(self._last['ok'])


compose_health = ComposeHealth()


async def probe_text_model() -> dict[str, Any]:
    """One tiny live Token Factory call, reported as a status not a guess.

    The demo's compose failures currently fall back to ``text_echo`` and leave
    only a server-side warning: an operator can see that the model did not run
    but not why. This makes the provider's own answer visible in one request —
    401/402/404, an empty reply, or a DNS/timeout failure — with the key
    redacted. It is deliberately a separate, explicit call: a diagnostic must
    not spend credit on every health poll, and it must not overwrite the
    last-compose record that explains a real reminder.
    """
    started = time.monotonic()

    def report(status: int, **fields: Any) -> dict[str, Any]:
        return {
            'ok': status == 200,
            'http_status': status,
            'model': ZIV_TEXT_MODEL,
            'base_url': NEBIUS_BASE_URL.rstrip('/'),
            'latency_ms': round((time.monotonic() - started) * 1000),
            'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            **fields,
        }

    if not NEBIUS_API_KEY:
        return report(503, error='no_key', provider_status=None,
                      detail='NEBIUS_API_KEY is not set on this relay; scheduled intents fire verbatim as text_echo.')
    if not ZIV_TEXT_MODEL:
        return report(503, error='no_model', provider_status=None,
                      detail='ZIV_TEXT_MODEL is empty; the relay has no model id to call.')
    try:
        import httpx
    except ImportError:
        return report(503, error='no_httpx', provider_status=None,
                      detail='httpx is not installed; the relay cannot make provider calls.')

    # The same switch the compose path sends: without it the probe's 8-token
    # budget goes entirely to `reasoning` and the diagnostic reads content:
    # null (previously reported as the sample "None", a false green light).
    payload = {
        'model': ZIV_TEXT_MODEL,
        'messages': [{'role': 'user', 'content': 'Reply with the single word: ok'}],
        'max_tokens': 8,
        'temperature': 0.0,
        'chat_template_kwargs': {'enable_thinking': False},
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                NEBIUS_BASE_URL.rstrip('/') + '/chat/completions',
                json=payload,
                headers={'Authorization': f'Bearer {NEBIUS_API_KEY}'},
            )
    except httpx.HTTPError as exc:
        return report(502, error='unreachable', provider_status=None,
                      detail=_redact(f'{type(exc).__name__}: {exc}'))

    if resp.status_code != 200:
        return report(502, error='provider_error', provider_status=resp.status_code,
                      detail=_redact(resp.text[:300]))
    try:
        raw = resp.json()['choices'][0]['message']['content']
    except (KeyError, IndexError, ValueError):
        return report(502, error='bad_reply', provider_status=resp.status_code,
                      detail='Token Factory answered 200 without choices[0].message.content.')
    if raw is None:
        return report(502, error='bad_reply', provider_status=resp.status_code,
                      detail='Token Factory answered 200 with content: null — the model produced reasoning only, so no line can play.')
    sample = str(raw).strip()
    if not sample:
        return report(502, error='empty_reply', provider_status=resp.status_code,
                      detail='The model answered 200 with an empty line.')
    return report(200, error=None, provider_status=resp.status_code, sample=sample[:80])


async def compose_reminder_line(intent: str) -> str:
    """Ask the model for the one line this reminder should play.

    The reminder the caller scheduled is an *intent* ("meds at nine"), not a
    finished sentence — turning it into the line a wrist reads is exactly the
    work an agent should do while nobody is chatting. The model's own words
    are what plays; nothing here invents or templates them, and the line is
    guaranteed to fit the band's spell cap in full (``compose_band_line``).

    Every attempt is recorded content-free for health, including the provider's
    refusal: a reminder that plays verbatim because the key has no credit must
    not look like a keyless run.
    """
    try:
        line = await compose_band_line(intent)
    except HTTPException as exc:
        detail = str(exc.detail)
        # Report the provider's own status when there is one (401/402/404);
        # the relay's 502 only says "compose failed", which is the number the
        # operator already knows. Transport failures keep the relay status.
        match = re.match(r'Token Factory error (\d{3}):', detail)
        compose_health.record(
            ok=False,
            status=int(match.group(1)) if match else exc.status_code,
            error=_compose_error_kind(detail), detail=detail, secret=intent,
        )
        raise
    except Exception as exc:
        compose_health.record(ok=False, error='exception',
                              detail=f'{type(exc).__name__}: {exc}', secret=intent)
        raise
    compose_health.record(ok=True, status=200)
    return line

async def deliver_inbox_one(session: RelaySession | None = None) -> dict[str, Any] | None:
    """Deliver the oldest pending inbox message on one band's stream.

    Marked delivered only *after* the close plays — a band vanishing
    mid-delivery leaves the message pending (redelivery, never loss).

    Delivery owns the haptic channel exactly the way a turn does
    (``gate.reserve()``): an inbox entry is already durable, so it must not
    interleave into a turn in flight, and — just as important — a *turn*
    must not interleave into the middle of a stored message. If the channel
    is already held the delivery declines and returns ``None``, leaving the
    entry pending for the next attach; nothing is lost, because nothing was
    touched. Two deliveries racing the same oldest entry are serialized by
    the relay-wide inbox lock, so the peek and the mark cannot straddle each
    other — even when the two bands belong to different sessions (the inbox
    is the wearer's, not a tab's: one entry is delivered exactly once).

    After the entry's close it drains the gate queue: texts that arrived
    while a stored backlog played have already cued on the wrist, and this
    is the owner that owes them their content.

    Every replay is a self-naming turn: the entry's source picks the mark
    kind (a stored reminder replays with the reminder's triple-pulse tail,
    any other stored message with the message's double-tap), so the wrist
    feels who is calling — and what kind of event it was — before the
    stored content arrives.

    ``session`` picks the band that plays it (default: this task's session).
    """
    token = _SESSION_CTX.set(session or _current_session())
    try:
        async with _inbox_lock:
            return await _deliver_inbox_one()
    finally:
        _SESSION_CTX.reset(token)

async def _deliver_inbox_one() -> dict[str, Any] | None:
    """``deliver_inbox_one``'s work, under its session and the inbox lock."""
    sess = _current_session()
    async with sess.lock:
        if not sess.gate.reserve():
            return None
        owed: list[str] = []
        released = False
        try:
            entry = inbox.peek_one()
            if entry is None:
                released = True
                await _play_drained(sess.gate.close_event(), owed)
                return None
            source = str(entry.get('source', 'message'))
            kind = 'reminder' if source == 'scheduled' else 'message'
            await _play_prefix_mark(kind, str(entry.get('text', '')))
            await _play_cells_and_close(str(entry.get('text', '')), note=True)
            owed = []
            inbox.mark_delivered(entry)
            released = True
            await _play_drained(sess.gate.close_event(), owed)
        except BaseException:
            for stranded in owed if released else [*owed, *sess.gate.abort()]:
                inbox.offer(stranded, source='queued')
            raise
    return entry

async def run_message_turn(text: str, *, source: str='message', prefix_mark: str | None=None, session: RelaySession | None=None) -> dict[str, Any]:
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

    ``session`` chooses whose hub/gate this turn drives — a message posted for
    tab A plays on A's wires only. Unset means this task's session, else the
    default session (the pre-session behaviour, kept for direct drivers).
    """
    token = _SESSION_CTX.set(session or _current_session())
    try:
        return await _run_message_turn(text, source=source, prefix_mark=prefix_mark)
    finally:
        _SESSION_CTX.reset(token)

async def _run_message_turn(text: str, *, source: str='message', prefix_mark: str | None=None) -> dict[str, Any]:
    """The turn pump itself; ``run_message_turn`` owns the session context."""
    sess = _current_session()
    if sess.hub.count == 0:
        entry = inbox.offer(text, source=source)
        return {'event': 'inbox:stored', 'stored': True, 'inbox_pending': inbox.count(), 'at': entry['at']}
    decision = sess.gate.admit(text)
    if decision.event_type == 'message:rejected':
        queue_rejections.record(str(decision.payload.get('reason', 'queue_full')))
        cap = int(decision.payload.get('cap', MessageGate.MAX_QUEUED))
        raise HTTPException(status_code=429, detail=f'message rejected: the replay queue is full ({cap} queued) — the wearer releases it after the current turn; try again later')
    if decision.event_type != 'message:play':
        await _push(haptic_frame(PATTERN_MESSAGE_CUE, why='queued'))
        return {'event': decision.event_type, 'queued': True, 'queue_len': len(sess.gate)}
    owed: list[str] = [text]
    turn: TurnTimeline | None = None
    released = False
    try:
        async with sess.lock:
            # Hold the channel for the whole turn, prefix mark included. Without
            # this an arrival during the name mark sees a free gate and becomes
            # a second main turn racing the turn lock — the recording's 8 fills
            # exposed it (they played one by one instead of queueing).
            if decision.event_type == 'message:play':
                sess.gate.reserve()
            if prefix_mark is not None:
                await _play_prefix_mark(prefix_mark, text)
            turn = TurnTimeline(sess.gate, text=text)

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
            await _play_cells_and_close(text, free_fn=lambda: len(sess.gate) == 0)
            owed.pop(0)
            replay = turn.finish_playback(now_s=round(time.monotonic() - t0, 1))
            drained = replay[1:]
            released = True
            await _play_drained(drained, owed)
            _telemetry.record(label='message_turn', seconds=turn.seconds, retries=turn.retries, source=source, queued=len(drained))
            return {'event': 'turn_complete', 'seconds': turn.seconds, 'events': [ev.event_type for ev in turn.events], 'drained': len(drained)}
    except BaseException as exc:
        if not released:
            owed.extend(sess.gate.abort())
        for pending_text in owed:
            inbox.offer(pending_text, source=source)
        _telemetry.record(label='message_turn_aborted', seconds=0.0, retries=turn.retries if turn is not None else 0, source=source, reason=type(exc).__name__, stranded=len(owed))
        LOGGER.warning('turn_aborted source=%s reason=%s stranded=%d — gate released, undelivered texts stored in the inbox', source, type(exc).__name__, len(owed))
        raise

@app.websocket('/ws')
async def ws_device(ws: WebSocket, token: str | None=Query(default=None),
                    session: str | None=Query(default=None)) -> None:
    """The device transport: attach, greet, drain, detach.

    ``?session=<id>`` selects which band's stream this socket joins. The
    client makes one id per tab, so two open tabs have two independent gates
    and never hear each other's turns; omitting the id joins the ``default``
    session (one-band behaviour, used by curl, the demo scripts and the
    pre-session tests).

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
    try:
        relay_session = sessions.get(session)
    except SessionIdError:
        await ws.close(code=4400)
        return
    except SessionLimit:
        await ws.close(code=4429)
        return
    await ws.accept()
    await relay_session.hub.attach(ws)
    sessions.touch(relay_session)
    try:
        pending = inbox.count()
        control_state = {'loop_running': _schedule_task is not None and (not _schedule_task.done()), 'loop_started': _schedule_loop_started, 'iface': _schedule_loop_iface is not None}
        await ws.send_text(json.dumps({'type': 'hello', 'session': relay_session.session_id, 'devices': relay_session.hub.count, 'spec_version': timing.SPEC_VERSION, 'patterns': list(timing.PATTERN_IDS), 'mark': timing.PREFIX_MARK, 'inbox_pending': pending, 'control': control_state}, ensure_ascii=False))
        if pending:
            try:
                while await deliver_inbox_one(relay_session) is not None:
                    pass
            except _NoDevices:
                pass
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=WS_HEARTBEAT_S)
            except asyncio.TimeoutError:
                await relay_session.hub.broadcast({'type': 'heartbeat', 'control': control_state})
    except WebSocketDisconnect:
        pass
    finally:
        relay_session.hub.detach(ws)
        sessions.release(relay_session)

def _http_session(raw: Any) -> RelaySession:
    """Resolve the session a content request targets, or fail loudly.

    No session id means the band currently in use (``active``), not the
    empty ``default``: an anonymous sender is addressing the wearer. An
    explicit id is honored exactly, and only that band hears the turn.
    """
    if not str(raw or '').strip():
        return sessions.active()
    try:
        return sessions.get(raw)
    except SessionIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SessionLimit as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post('/api/ziv/message')
async def post_message(body: dict[str, Any], authorization: str | None=Header(default=None),
                       session: str | None=Query(default=None),
                       x_ziv_session: str | None=Header(default=None)) -> JSONResponse:
    """One inbound message → that session's gate → its WS frames only.

    The browser sends its id in ``X-Ziv-Session``; ``session`` is accepted in
    the query string or the body too, so curl/API callers can choose a band.
    Without one, the band in use gets the message (see
    ``SessionRegistry.active``) — an anonymous sender targets the wearer.
    """
    _authorized_http(authorization)
    text = str(body.get('text', '')).strip()
    if not text:
        raise HTTPException(status_code=422, detail='text is required')
    relay_session = _http_session(
        x_ziv_session or session or body.get('session')
    )
    try:
        result = await run_message_turn(text, source='message', session=relay_session)
    except _NoDevices as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post('/api/ziv/compose')
async def compose_once(body: dict[str, Any], authorization: str | None = Header(default=None),
                       x_nebius_key: str | None = Header(default=None),
                       session: str | None = Query(default=None),
                       x_ziv_session: str | None = Header(default=None)) -> JSONResponse:
    """One live model compose paid for by the caller's own key.

    The judge pastes a Nebius Token Factory key in the console; the browser
    sends it in ``X-Nebius-Key`` for this request only. The key is used for
    exactly one provider call, never written to the environment, the stores,
    the logs or health, and scrubbed from any provider text before it is
    returned. The model's line then takes the ordinary turn path on the
    caller's own band, labelled ``text_live`` — the proof a scheduled intent
    gives, without needing the relay owner's credit.

    This is deliberately one-shot: a key supplied now is not attached to a
    reminder that fires later, because that would mean holding a stranger's
    credential in memory for minutes or hours.
    """
    _authorized_http(authorization)
    key = str(x_nebius_key or '').strip()
    intent = str(body.get('intent') or '').strip()
    if not key:
        raise HTTPException(status_code=422, detail='X-Nebius-Key is required — paste a Nebius Token Factory key in the console')
    if not intent:
        raise HTTPException(status_code=422, detail='intent is required')
    if len(intent) > 200:
        raise HTTPException(status_code=422, detail='intent is too long (200 characters max)')
    relay_session = _http_session(
        x_ziv_session or session or body.get('session')
    )
    started = time.monotonic()

    def report(status: int, **fields: Any) -> JSONResponse:
        return JSONResponse(
            {'ok': status == 200, 'model': ZIV_TEXT_MODEL,
             'latency_ms': round((time.monotonic() - started) * 1000), **fields},
            status_code=status,
        )

    try:
        line = await compose_band_line(intent, api_key=key)
    except HTTPException as exc:
        detail = _redact(str(exc.detail), key)
        match = re.match(r'Token Factory error (\d{3}):', detail)
        kind = ('unreachable' if detail.startswith('Token Factory unreachable')
                else 'provider_error' if match
                else 'too_long' if detail.startswith('model answered')
                else 'compose_failed')
        return report(502, error=kind,
                      provider_status=int(match.group(1)) if match else None,
                      detail=detail)
    except Exception as exc:
        return report(502, error='exception', provider_status=None,
                      detail=_redact(f'{type(exc).__name__}: {exc}', key))

    text = line
    result = await run_message_turn(
        text, source='text_live', prefix_mark='reminder', session=relay_session,
    )
    return JSONResponse({
        'ok': True, 'text': text, 'source': 'text_live',
        'session': relay_session.session_id, 'model': ZIV_TEXT_MODEL,
        'latency_ms': round((time.monotonic() - started) * 1000),
        'result': result,
    })


@app.post('/inject/audio')
async def inject_audio(body: dict[str, Any], authorization: str | None=Header(default=None),
                       session: str | None=Query(default=None),
                       x_ziv_session: str | None=Header(default=None)) -> JSONResponse:
    """The Omni spike's seam (week 1), now real: mic audio → transcript → turn.

    The PWA records the mic (MediaRecorder) and posts
    ``{"audio_b64": "…", "mime": "webm", "lang": "en"}``. Without an
    audio-capable endpoint configured this answers 503 — a refusal, never a
    silent failure. ``{"simulate": "<text>"}`` is the keyless path the demo
    runs; it takes the *same turn* a typed message would, so cues, ticks,
    cells, close and the queue are all exercised either way.
    """
    _authorized_http(authorization)
    relay_session = _http_session(
        x_ziv_session or session or body.get('session')
    )
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
            await _announce_error(f'transcription failed ({exc.status_code})',
                                  session=relay_session)
            raise
        source = 'audio_omni'
    try:
        result = await run_message_turn(text, source=source, session=relay_session)
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
    return {'status': 'ok', 'service': 'Ziv relay v1 (dev band + memory)', 'devices': sessions.total_devices(), 'sessions': sessions.describe(), 'spec_version': timing.SPEC_VERSION, 'fake_model_seconds': FAKE_MODEL_SECONDS, 'auth': bool(ZIV_RELAY_TOKEN), 'text': {'key_set': bool(NEBIUS_API_KEY), 'base_url': NEBIUS_BASE_URL.rstrip('/'), 'model': ZIV_TEXT_MODEL, 'configured': agent_path_configured(), 'available': agent_path_available(), 'last_compose': compose_health.snapshot()}, 'omni': {'key_set': _omni_configured(), 'model': ZIV_OMNI_MODEL, 'configured': bool(ZIV_OMNI_MODEL)}, 'queue_rejections': queue_rejections.snapshot(), 'gate_queue': sessions.total_queued(), 'gate_queue_cap': MessageGate.MAX_QUEUED, 'inbox_pending': inbox_pending, 'inbox_cap': INBOX_CAP, 'inbox_evicted': inbox.evictions(), 'schedule_pending': schedule_pending, 'schedule_cap': SCHEDULE_CAP, 'schedule_evicted': scheduled.evictions(), 'schedule_corrupt': 'schedule' in corrupt, 'prefs': prefs, 'store_problems': corrupt, 'turns': _telemetry.stats(), 'schedule_loop': {'running': _schedule_task is not None and (not _schedule_task.done()), 'poll_s': 1.0, 'last_fire_at': _telemetry.last('scheduled_reminder_fired')}}


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
