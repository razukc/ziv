"""agent/ziv_relay.py — the Ziv relay seam: the real behavior a future relay builds on.



This is the honest home of the Ziv relay seam, and it is self-standing: it

imports only the shared primitives (agent/ports.py — retry config, the

telemetry ring) and defines its own event vocabulary (TurnEvent, below). It

imports no SkillForge compose scaffold, and the SkillForge backend does not

import this file — the two tracks build, test, and run independently and

meet only at the shared primitives. The Ziv seam is:

* MessageGate — the queue-don't-interrupt policy (plan §4 invariant 4).
  The haptic channel is serial: when content is playing, an incoming message
  may announce itself (attention cue only) and queues its text; the wearer —
  not the sender — releases the queue after the end-of-message close.
  Concurrency (harden-against-concurrent-transports): one wrist, one playback
  loop, but transports call admit/close_event from concurrent tasks and
  threads, so the gate serializes its decisions internally with a lock and
  keeps the queue bounded — overflow is a sender-visible ``message:rejected``
  decision, never a silent drop and never an unbounded backlog.

* TurnTimeline — the turn state machine and the executable form of the

  interaction invariants (plan §4): every wearer-visible event a turn

  produces, in order — kind cue, processing ticks while the model works, the

  model result, the end-of-message close, then the gate release and any queued

  replays. Wired through MessageGate; proven end-to-end in

  agent/tests_ziv/test_ziv_e2e.py.

* The lifecycle event vocabulary (invariants 2—3): every relay turn moves

  accepted → processing → playing | error. The haptic side of those states

  is in the timing spec (processing, the error long-buzz, and the

  end-of-message close; spec v3).



Status today: the Ziv track has the *output/timing/sequencer* side

(firmware/haptic_out/, tools/haptic_timing.py, the phone mock, and the docs

plan set). The *input/brain/transport* side of the relay — mic/audio-in path,

braille-chord input, WebSocket/SSE transport, ESP-IDF FreeRTOS task, Token

Factory Omni audio payload — does not exist yet. When it is built, the real

relay fills in the turn driver that drives MessageGate + TurnTimeline (a model

round-trip injected as a callable, fake or Token Factory).



The placeholder below (ZivRelayAdapter) is a labeled run_turn landing pad for

that future work; it is *not* what the dev-band server calls — the server

drives the real seam directly.

"""



from __future__ import annotations

import asyncio
import threading
from collections import deque

from typing import Any

from dataclasses import dataclass



from ports import TelemetryRing





# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------

# TurnEvent — the event vocabulary the Ziv seam emits

# ---------------------------------------------------------------------------



@dataclass

class TurnEvent:

    """One wearer-visible event a turn produces — the Ziv seam's vocabulary.



    Owned here, not borrowed from the SkillForge compose scaffold: the seam's

    events are haptic-lifecycle shaped (a kind cue, a processing tick, an

    error, the close, a replay decision) and carry none of the compose

    wrapper's fields. ``seconds``/``retries`` stay on the timeline, which

    counts them itself.

    """



    event_type: str

    payload: dict[str, Any]

# Lifecycle event kinds (plan §4 invariants 2–3; patterns live in the spec)

# ---------------------------------------------------------------------------

#

# One relay turn moves: accepted → processing → playing | error.

#

#   "processing"    — the turn is in flight; the device repeats the

#                     `processing` pattern (~every 2 s) until content or

#                     error plays. Latency may be slow, never silent.

#   "playback_done" — content finished; the `end-of-message` close plays and

#                     the event is over (invariant 2: cues mark the end too).

#   error paths reuse the existing `error` attention pattern (long-buzz).

#

# The patterns themselves resolve against docs/haptic-timing.json (spec v3) —

# the single source shared with the phone feel-tool and the firmware header.



KIND_PROCESSING = "processing"

KIND_PLAYBACK_DONE = "playback_done"



# The pattern ids these lifecycle events resolve to, as named in the timing

# spec (v3). Kept beside the kinds so a relay author reads the mapping once.

PATTERN_PROCESSING = "processing"

PATTERN_END_OF_MESSAGE = "end-of-message"

PATTERN_MESSAGE_CUE = "double-tap"

PATTERN_ERROR = "long-buzz"





class MessageGate:
    """Queue-don't-interrupt between incoming messages and playback.

    Implements plan §4 invariant 4: an incoming message during playback plays
    its attention cue only and queues its text; nothing barges into what the
    wearer is already reading, and the wearer — not the sender — releases the
    queue. Policy:

    * idle + message      → ``message:play`` (mark → attention tail → content)
    * playing + message   → ``attention:double-tap`` now; text queued
    * playing + full queue → ``message:rejected`` — the sender is told no,
      loudly (the dev-band server maps it to HTTP 429); the wearer feels
      nothing, and nothing is dropped silently or queued without bound
    * ``close_event()``   → playback is over (the end-of-message close has
      played, or the wearer resumed): the queue drains oldest-first as
      ``message:play`` results

    Thread discipline: one wrist, one playback loop, but concurrent
    transports (websocket + HTTP + audio) call ``admit``/``begin_playback``/
    ``close_event`` from different tasks and threads. The gate is the seam's
    serialization point: every decision is atomic under its reentrant lock,
    so a racing admit either queues, plays, or is rejected — it never
    corrupts the queue, vanishes, or doubles. The lock serializes
    *decisions*, not turns: the caller still drives one turn at a time (the
    server's turn lock does that).
    """

    #: Bound on the replay queue (plan §9: bounded memory everywhere). A
    #: human-scale backlog — queued messages replay immediately after the
    #: close, so more than a handful means the wearer stops reading them;
    #: better a loud rejection than a silent hour of backlog. Deliberately
    #: smaller than the inbox cap (INBOX_CAP = 20), which holds messages for
    #: *days* while no band is attached.
    MAX_QUEUED = 8

    def __init__(self) -> None:
        self._playing = False
        self._queue: deque[str] = deque()
        # Reentrant: a decision may call another gate method while holding
        # the lock; the lock is the seam's serialization point (docstring).
        self._lock = threading.RLock()

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)

    def begin_playback(self) -> None:
        """The playback loop reports that content is now on the motors."""
        with self._lock:
            self._playing = True

    def admit(self, text: str) -> TurnEvent:
        """Route one incoming message: play now, announce + queue, or reject.

        A queued message still gets its attention cue immediately — the
        wearer feels that something arrived (double-tap) — only its *content*
        waits. The decision, not the text, is what the shared layer renders.
        Atomic under the gate's lock: a concurrent admit either queues, plays,
        or is rejected; it never corrupts the queue or vanishes.
        """
        with self._lock:
            if not self._playing:
                return TurnEvent(
                    event_type="message:play",
                    payload={"text": text, "queued": False, "prefix": True},
                )
            if len(self._queue) >= self.MAX_QUEUED:
                # Bounded memory (plan §9): say no, loudly, rather than queue
                # without bound or drop the message silently. The caller owns
                # how the refusal reaches the sender (the dev-band server
                # answers HTTP 429); the wrist feels nothing.
                return TurnEvent(
                    event_type="message:rejected",
                    payload={
                        "text": text,
                        "queued": False,
                        "prefix": False,
                        "reason": "queue_full",
                        "cap": self.MAX_QUEUED,
                    },
                )
            self._queue.append(text)
            return TurnEvent(
                event_type="attention:double-tap",
                payload={"text": text, "queued": True, "prefix": True},
            )

    def close_event(self) -> list[TurnEvent]:
        """The event closed: end-of-message has played (or the wearer resumed).

        Drains the queue oldest-first, one ``message:play`` result per queued
        message — each still opens with its full prefix (invariant 1: no
        content without a kind cue, even queued). Empty list when nothing was
        waiting; closing an idle gate is a no-op, not an error. Atomic under
        the gate's lock: a close never interleaves with a racing admit.
        """
        with self._lock:
            self._playing = False
            drained: list[TurnEvent] = []
            while self._queue:
                drained.append(
                    TurnEvent(
                        event_type="message:play",
                        payload={
                            "text": self._queue.popleft(),
                            "queued": False,
                            "prefix": True,
                        },
                    )
                )
            return drained


# ---------------------------------------------------------------------------

# TurnTimeline — the turn state machine (the executable invariants)

# ---------------------------------------------------------------------------



# States of one turn, in wearer-visible order.



#: The turn exists; its opening kind cue has been decided (invariant 1).

ACCEPTED = "accepted"

#: The model round-trip is in flight; ``processing`` repeats (invariant 3).

PROCESSING = "processing"

#: Content is on the motors; the gate holds the channel (invariant 4).

PLAYING = "playing"

#: The close has played; the event is over (invariant 2); queue releases.

CLOSED = "closed"

#: The model failed; ``long-buzz`` played; the turn is over.

ERROR = "error"



#: Default cadence of the ``processing`` pattern while a turn is in flight

#: (plan §4 invariant 3: "repeats ~every 2 s"). Seconds, not ms — the

#: relay's clocks are seconds.

PROCESSING_EVERY_S = 2.0





class TurnTimeline:

    """One relay turn as the wearer feels it — the six invariants, in code.



    The device does not implement the lifecycle itself; it *renders* the

    events this machine emits. The timeline owns:



    * the ordering — a kind cue before any content (inv 1), ``processing``

      while waiting (inv 3), the ``end-of-message`` close before the gate

      releases (inv 2), queued replays after the close (inv 4);

    * the clock — ``poll()`` emits the next ``processing`` event every

      ``PROCESSING_EVERY_S`` while the model round-trip runs, so latency is

      slow-but-never-silent without the caller wiring a timer;

    * the gate — ``PLAYING`` opens ``MessageGate``; ``finish_playback()``

      plays the close and releases the queue, returning the drained replays.

    Not thread-safe on purpose (one wrist, one turn — a turn object has a
    single driver, the pump that holds the server's turn lock). Concurrent
    transports serialize on the *gate* it holds: MessageGate is thread-safe
    (see its docstring), so arrivals racing a turn queue, play, or get
    rejected atomically while this timeline drives one turn.

    """



    def __init__(

        self,

        gate: MessageGate,

        *,

        text: str,

        cue: str = "message:play",

        processing_every_s: float = PROCESSING_EVERY_S,

    ) -> None:

        self._gate = gate

        self.text = text

        self._cue = cue

        self._processing_every_s = processing_every_s

        self.state = ACCEPTED

        self._last_processing_at: float | None = None

        self._seconds = 0.0

        self._retries = 0

        self._events: list[TurnEvent] = [self._cue_event()]



    # -- events (each is one TurnEvent the device renders) ---------------



    def _cue_event(self) -> TurnEvent:

        return TurnEvent(

            event_type=self._cue,

            payload={"text": self.text, "state": self.state, "prefix": True},

        )



    def _processing_event(self) -> TurnEvent:

        return TurnEvent(

            event_type=f"attention:{PATTERN_PROCESSING}",

            payload={"state": self.state, "pattern": PATTERN_PROCESSING},

        )



    def _error_event(self) -> TurnEvent:

        return TurnEvent(

            event_type=f"attention:{PATTERN_ERROR}",

            payload={"state": self.state, "pattern": PATTERN_ERROR},

        )



    def _close_event(self) -> TurnEvent:

        return TurnEvent(

            event_type=f"lifecycle:{KIND_PLAYBACK_DONE}",

            payload={"state": self.state, "pattern": PATTERN_END_OF_MESSAGE},

        )



    # -- observation -------------------------------------------------------



    @property

    def events(self) -> list[TurnEvent]:

        """Every event so far, in order — the wearer-visible journey."""

        return list(self._events)



    @property

    def seconds(self) -> float:

        return round(self._seconds, 1)



    @property

    def retries(self) -> int:

        return self._retries



    # -- driving -----------------------------------------------------------



    def begin_processing(self, now_s: float) -> TurnEvent:

        """The model round-trip starts: the first ``processing`` cue now."""

        assert self.state == ACCEPTED, f"begin_processing from {self.state}"

        self.state = PROCESSING

        self._last_processing_at = now_s

        ev = self._processing_event()

        self._events.append(ev)

        return ev



    def poll(self, now_s: float) -> TurnEvent | None:

        """The clock while PROCESSING: another cue when the cadence is due.



        Emits at most one event per call and never re-arms a finished turn.

        The relay's loop calls this on its natural tick — a websocket ping,

        an epoll wake, a timer — no dedicated timer thread.

        """

        if self.state != PROCESSING or self._last_processing_at is None:

            return None

        if now_s - self._last_processing_at < self._processing_every_s:

            return None

        self._last_processing_at = now_s

        ev = self._processing_event()

        self._events.append(ev)

        return ev



    def record_retry(self, attempt: int, error: BaseException) -> None:

        """A healed provider blip (the shared on_retry hook shape).



        The wrist learns nothing — retrying is relay-internal noise — but the

        turn's telemetry carries it, like any shared-layer turn.

        """

        self._retries = attempt



    def begin_playback(self) -> TurnEvent:

        """Content reaches the motors: the cue result, and the gate closes."""

        assert self.state == PROCESSING, f"begin_playback from {self.state}"

        self.state = PLAYING

        self._gate.begin_playback()

        ev = self._cue_event()

        self._events.append(ev)

        return ev



    def fail(self) -> TurnEvent:

        """The turn failed: ``long-buzz`` says so — latency with an ending."""

        assert self.state in (ACCEPTED, PROCESSING), f"fail from {self.state}"

        self.state = ERROR

        ev = self._error_event()

        self._events.append(ev)

        return ev



    def finish_playback(self, *, now_s: float | None = None) -> list[TurnEvent]:

        """The close, then the release: end-of-message, then the queue.



        ``now_s`` closes the turn's wall time when the caller has a clock.

        Returns the close event followed by one ``message:play`` per queued

        message (FIFO, each with its prefix — invariant 1 holds for queued

        content). Nothing queued: the close alone, and the wrist goes quiet.

        """

        assert self.state == PLAYING, f"finish_playback from {self.state}"

        if now_s is not None:

            self._seconds = now_s

        self.state = CLOSED

        out = [self._close_event()]

        self._events.append(out[0])

        out.extend(self._gate.close_event())

        self._events.extend(out[1:])

        return out



    def replay_close(self) -> TurnEvent:

        """The close vocabulary for a drained replay, from the same machine.



        A queued message replays as its own full event after this turn's

        close (invariants 1+2 for queued content); its closing beat is the

        same ``end-of-message`` event this timeline just played — the

        renderer calls this instead of hand-building a close, so the replay

        cannot drift from the turn's own close.

        """

        return self._close_event()



    def take_events(self) -> list[TurnEvent]:

        """Hand the journey to the renderer and forget it (bounded memory)."""

        events, self._events = self._events, []

        return events





class ZivRelayAdapter:

    """Placeholder run_turn landing pad for the future Ziv relay.



    A labeled TODO shape, *not* what the dev-band server calls: the server

    drives the real seam (MessageGate + TurnTimeline) directly through

    run_message_turn. The adapter is self-standing — it inherits nothing and

    imports no SkillForge compose scaffold; its contract is the seam above.



    When the relay is built, the real turn driver will own:



    * the device input path (mic / chord input / etc.),

    * the model round-trip, emitting the lifecycle states in order —

      accepted → processing → playing | error (invariant 3: the

      `processing` pattern repeats while the turn is in flight; latency may

      be slow, never silent),

    * the device output path (DRV2605L timeline / etc.), routed through

      MessageGate so playback is never interrupted (invariant 4),

    * and its own event vocabulary (TurnEvent, above) so the shared

      primitives (telemetry, SSE) can render it.

    """



    def is_ready(self) -> bool:

        # Real implementation: check device / transport readiness.

        return False



    def run_turn(

        self,

        input_event: Any,

        *,

        on_retry: Any = None,

        telemetry: TelemetryRing | None = None,

    ) -> TurnEvent:

        """One turn: read input, run the model/policy, hand back the event.



        Deliberately duck-typed — no config object, no compose wrapper. The

        relay's retry policy is its own; the telemetry ring is the one

        shared primitive both tracks use.

        """

        raise NotImplementedError(

            "Ziv relay adapter is a placeholder seam; implement run_turn() "

            "when the relay is built."

        )





def make_ziv_relay_adapter() -> ZivRelayAdapter:

    """Factory for the placeholder run_turn landing pad.



    Exists so the e2e canned adapter has a named base to subclass and so the

    file surfaces one obvious "implement this when the relay is built" hook.

    It is *not* used by the dev-band server, which drives MessageGate +

    TurnTimeline directly. When the relay is built, this factory would inject

    the device/transport dependencies into the real turn driver.

    """

    return ZivRelayAdapter()