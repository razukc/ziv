"""ziv.relay.service — the Relay: store + clock + composer + connected devices.

Every public method is one unit of work: load the slice, call the core,
write within one transaction, dispatch the effects. The scheduler's ``tick``
is a method the loop calls; tests call it directly with their own ``now``.
Nothing here keeps message content anywhere but the outbox rows.
"""
from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

import ziv
from ziv.core import admission, outbox, schedule, spec
from ziv.core.credentials import (
    hash_secret,
    new_enroll_code,
    new_id,
    new_token,
    new_utterance_id,
)
from ziv.core.model import (
    SCOPE_ADMIN,
    SCOPES,
    Device,
    OutboxEntry,
    Refusal,
    ScheduleEntry,
    Sender,
    to_datetime,
    to_epoch,
)
from ziv.core.outbox import (
    DeviceSlot,
    Effect,
    IllegalTransition,
    LogEvent,
    NotifySender,
    SendBody,
    SendCancel,
    SendOpen,
)
from ziv.store import RetentionPolicy, Store
from ziv.wire import (
    WIRE_VERSION,
    Control,
    CreateSender,
    DeviceView,
    EnrollBody,
    EnrollCodeResponse,
    EnrollResponse,
    Health,
    Hello,
    HelloAck,
    InputText,
    Kind,
    Nack,
    Ping,
    Played,
    Pong,
    PrefChanged,
    Prefs,
    PrefSet,
    Profile,
    Progress,
    ProtocolError,
    Reason,
    ReplyView,
    ScheduleBody,
    ScheduleView,
    SenderView,
    Source,
    State,
    SubmitUtterance,
    Utterance,
    UtteranceBody,
    UtteranceCancel,
    UtteranceOpen,
    UtteranceView,
)

from .clock import Clock
from .composer import ComposeError, Composer
from .devices import DeviceConn, DeviceRegistry
from .settings import Settings

ADMIN_META_KEY = "admin_token_hash"
ADMIN_RATE_PER_MIN = 600
SCHEDULE_SENDER = "schedule"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling the HTTP API, and for which wearer."""

    wearer: str
    sender_id: str
    label: str
    scopes: frozenset[str]
    rate_per_min: int
    admin: bool = False

    def allows(self, scope: str) -> bool:
        return self.admin or scope in self.scopes or SCOPE_ADMIN in self.scopes


class TokenBucket:
    def __init__(self, per_min: int, now: float) -> None:
        self.capacity = float(max(1, per_min))
        self.rate = self.capacity / 60.0
        self.tokens = self.capacity
        self.last = now

    def take(self, now: float) -> bool:
        self.tokens = min(self.capacity, self.tokens + max(0.0, now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


def view_of(e: OutboxEntry) -> UtteranceView:
    return UtteranceView(
        id=e.id, state=e.state, kind=e.utterance.kind, words=list(e.utterance.words),
        source=e.utterance.source, duration_ms=e.duration_ms, budget_ms=e.budget_ms,
        device=e.device, reason=e.reason, created=to_datetime(e.created), updated=to_datetime(e.updated),
        lossy=e.lossy,
    )


def schedule_view(s: ScheduleEntry) -> ScheduleView:
    return ScheduleView(id=s.id or 0, fire_at=to_datetime(s.fire_at), kind=s.kind, composed=s.composed, label=s.label)


class Relay:
    def __init__(self, settings: Settings, store: Store, clock: Clock, composer: Composer) -> None:
        self.settings = settings
        self.store = store
        self.clock = clock
        self.composer = composer
        self.devices = DeviceRegistry()
        self.retention = RetentionPolicy.from_days(settings.retention_days)
        self._buckets: dict[str, TokenBucket] = {}
        self._compose_tasks: dict[str, asyncio.Task] = {}
        self._last_prune: float | None = None
        self._seq = 0
        self.started = False

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        now = self.clock.now()
        self.store.migrate(now)
        self.store.wearers.ensure(self.settings.default_wearer, self.settings.wearer_name, now)
        self.store.integrity_check(now)
        self.event("start", counts={"spec_version": spec.spec_version(), "wire_version": WIRE_VERSION})
        self.started = True

    def close(self) -> None:
        for task in list(self._compose_tasks.values()):
            task.cancel()
        self.store.close()

    # --- events and effects -------------------------------------------------

    def event(self, kind: str, *, wearer: str | None = None, reason: Reason | str | None = None,
              counts: dict | None = None, detail: str | None = None) -> None:
        self.store.events.append(self.clock.now(), kind, wearer=wearer, reason=reason, counts=counts, detail=detail)

    def _refused(self, wearer: str, refusal: Refusal, what: str = "utterance") -> Refusal:
        numeric = {k: v for k, v in (refusal.detail or {}).items() if isinstance(v, (int, float))}
        self.event("refused", wearer=wearer, reason=refusal.reason, counts=numeric, detail=what)
        return refusal

    def apply(self, effects: Iterable[Effect]) -> None:
        now = self.clock.now()
        for fx in effects:
            if isinstance(fx, SendOpen):
                self._send(fx.device, UtteranceOpen(utterance=fx.utterance), fx.utterance.wearer)
            elif isinstance(fx, SendBody):
                frame = UtteranceBody(id=fx.id, words=list(fx.words), source=fx.source, error=fx.error)
                self._send(fx.device, frame, None)
            elif isinstance(fx, SendCancel):
                self._send(fx.device, UtteranceCancel(id=fx.id, reason=fx.reason), None)
            elif isinstance(fx, LogEvent):
                self.store.events.append(now, fx.kind, wearer=fx.wearer, reason=fx.reason, counts=dict(fx.counts))
            elif isinstance(fx, NotifySender):
                pass  # senders poll GET /utterances/{id}; the state change is already durable

    def _send(self, device_id: str, frame, wearer: str | None) -> None:
        if not self.devices.send(device_id, frame):
            conn = self.devices.get(device_id)
            self.event("send_dropped", wearer=wearer or (conn.wearer if conn else None),
                       reason=Reason.device_gone, counts={"overflow": int(bool(conn and conn.overflow))})

    # --- auth ---------------------------------------------------------------

    def _admin_matches(self, token: str) -> bool:
        if self.settings.admin_token and hmac.compare_digest(token, self.settings.admin_token):
            return True
        stored = self.store.meta_get(ADMIN_META_KEY)
        return bool(stored) and hmac.compare_digest(hash_secret(token), stored)

    def authenticate(self, token: str | None) -> Principal | None:
        if not token:
            return None
        if self._admin_matches(token):
            return Principal(self.settings.default_wearer, "admin", "admin", frozenset(SCOPES), ADMIN_RATE_PER_MIN, True)
        sender = self.store.senders.find_by_token(token)
        if sender is None:
            return None
        return Principal(sender.wearer, sender.id, sender.label, sender.scopes, sender.rate_per_min)

    def rate_check(self, principal: Principal) -> Refusal | None:
        now = self.clock.monotonic()
        bucket = self._buckets.get(principal.sender_id)
        if bucket is None or bucket.capacity != float(max(1, principal.rate_per_min)):
            bucket = self._buckets[principal.sender_id] = TokenBucket(principal.rate_per_min, now)
        if bucket.take(now):
            return None
        refusal = Refusal(Reason.rate_limited, f"more than {principal.rate_per_min} requests a minute",
                          {"rate_per_min": principal.rate_per_min})
        self.event("rate_limited", wearer=principal.wearer, reason=Reason.rate_limited)
        return refusal

    def mint_admin_token(self) -> str | None:
        """Create the admin token once, when none is configured or stored. Returns the plaintext or None."""
        if self.settings.admin_token or self.store.meta_get(ADMIN_META_KEY):
            return None
        token = new_token()
        with self.store.tx(immediate=True):
            self.store.meta_set(ADMIN_META_KEY, hash_secret(token))
        self.event("admin_token_minted")
        return token

    def _new_id(self, now: float) -> str:
        self._seq += 1
        return new_utterance_id(now, self._seq)

    # --- wearer context -----------------------------------------------------

    def _primary(self, wearer: str) -> Device | None:
        devices = self.store.devices.list(wearer)
        for d in devices:
            if d.primary:
                return d
        return devices[0] if devices else None

    def _profile_for(self, wearer: str, device_id: str | None = None) -> Profile:
        if device_id is not None:
            conn = self.devices.get(device_id)
            if conn is not None:
                return conn.profile
            d = self.store.devices.get(device_id)
            if d is not None:
                return d.profile
        primary = self._primary(wearer)
        return primary.profile if primary else Profile.six_actuator

    def _slots(self, wearer: str) -> list[DeviceSlot]:
        return [
            DeviceSlot(d.id, self.devices.is_connected(d.id), self.settings.device_capacity, d.primary, d.order)
            for d in self.store.devices.list(wearer)
        ]

    def _assign(self, wearer: str) -> None:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            before = self.store.outbox.active(wearer)
            after, fx = outbox.assign(before, self._slots(wearer), now)
            self.store.outbox.save_changed(before, after)
        self.apply(fx)

    # --- utterances (sender side) -------------------------------------------

    def submit(self, principal: Principal, body: SubmitUtterance) -> UtteranceView | Refusal:
        now = self.clock.now()
        wearer = principal.wearer
        lossy = False
        if body.words:
            words: Sequence[str] = body.words
        else:
            n = admission.normalise(body.text or "", allow_lossy=body.allow_lossy)
            if isinstance(n, Refusal):
                return self._refused(wearer, n)
            words, lossy = n.words, n.lossy
        try:
            utt = Utterance(
                id=self._new_id(now), wearer=wearer, kind=body.kind,
                **{"from": {"sender": principal.sender_id, "label": body.label or principal.label[:40]}},
                prefix=spec.prefix_for(body.kind), words=list(words), source=Source.sender,
                not_before=body.not_before, expires=body.expires, spec_version=spec.spec_version(),
            )
        except ValidationError as exc:
            return self._refused(wearer, Refusal(Reason.bad_request, "; ".join(e["msg"] for e in exc.errors())))
        prefs = self.store.prefs.get(wearer)
        measured = admission.check_budget(utt, self._profile_for(wearer), prefs.pace_ms, self.settings.budget_ms)
        if isinstance(measured, Refusal):
            return self._refused(wearer, measured)
        entry = OutboxEntry(utterance=utt, state=State.pending, created=now, updated=now,
                            duration_ms=measured, budget_ms=self.settings.budget_ms, lossy=lossy)
        with self.store.tx(immediate=True):
            active = self.store.outbox.active(wearer)
            result = outbox.admit(active, entry, self.settings.outbox_cap)
            if isinstance(result, Refusal):
                return self._refused(wearer, result)
            entry, fx = result
            self.store.outbox.insert(entry)
            before = active + [entry]
            after, fx2 = outbox.assign(before, self._slots(wearer), now)
            self.store.outbox.save_changed(before, after)
            entry = next(e for e in after if e.id == entry.id)
        self.apply(fx + fx2)
        return view_of(entry)

    def get_utterance(self, wearer: str, id: str) -> UtteranceView | Refusal:
        e = self.store.outbox.get(id)
        if e is None or e.wearer != wearer:
            return Refusal(Reason.not_found, "no such utterance")
        return view_of(e)

    def list_utterances(self, wearer: str, state: State | None = None, limit: int = 100) -> list[UtteranceView]:
        return [view_of(e) for e in self.store.outbox.list(wearer, state, limit)]

    def cancel_utterance(self, wearer: str, id: str, reason: Reason = Reason.cancelled_by_sender) -> UtteranceView | Refusal:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            e = self.store.outbox.get(id)
            if e is None or e.wearer != wearer:
                return Refusal(Reason.not_found, "no such utterance")
            try:
                ne, fx = outbox.cancel(e, reason, now)
            except IllegalTransition:
                return Refusal(Reason.conflict, f"already {e.state}", {"terminal": 1})
            self.store.outbox.save(ne)
        self.apply(fx)
        return view_of(ne)

    # --- schedule -----------------------------------------------------------

    def add_schedule(self, principal: Principal, body: ScheduleBody) -> ScheduleView | Refusal:
        now = self.clock.now()
        wearer = principal.wearer
        if body.text is not None:
            n = admission.normalise(body.text, allow_lossy=False)
            if isinstance(n, Refusal):
                return self._refused(wearer, n, "schedule")
            words = n.words
        else:
            words = ()
        row = ScheduleEntry(id=None, wearer=wearer, fire_at=to_epoch(body.fire_at) or now, kind=body.kind,
                            text=body.text, intent=body.intent, expires_after_s=body.expires_after_s,
                            created=now, label=body.label)
        # a text that can never fit is refused now, not at fire time
        probe = schedule.build_utterance(row, id=self._new_id(now), words=words, body_pending=not words,
                                         source=Source.sender, sender=SCHEDULE_SENDER)
        prefs = self.store.prefs.get(wearer)
        measured = admission.check_budget(probe, self._profile_for(wearer), prefs.pace_ms, self.settings.budget_ms)
        if isinstance(measured, Refusal):
            return self._refused(wearer, measured, "schedule")
        with self.store.tx(immediate=True):
            refusal = schedule.check_cap(self.store.schedule.count(wearer), self.settings.schedule_cap)
            if refusal is not None:
                return self._refused(wearer, refusal, "schedule")
            row = self.store.schedule.insert(row)
        self.event("scheduled", wearer=wearer, counts={"composed": int(row.composed), "words": len(words)})
        return schedule_view(row)

    def list_schedule(self, wearer: str) -> list[ScheduleView]:
        return [schedule_view(s) for s in self.store.schedule.list(wearer)]

    def get_schedule(self, wearer: str, id: int) -> ScheduleView | Refusal:
        s = self.store.schedule.get(id)
        if s is None or s.wearer != wearer:
            return Refusal(Reason.not_found, "no such schedule entry")
        return schedule_view(s)

    def delete_schedule(self, wearer: str, id: int) -> ScheduleView | Refusal:
        with self.store.tx(immediate=True):
            s = self.store.schedule.get(id)
            if s is None or s.wearer != wearer:
                return Refusal(Reason.not_found, "no such schedule entry")
            self.store.schedule.delete(id, wearer)
        self.event("unscheduled", wearer=wearer)
        return schedule_view(s)

    # --- prefs --------------------------------------------------------------

    def get_prefs(self, wearer: str) -> Prefs:
        return self.store.prefs.get(wearer).to_wire()

    def set_prefs(self, wearer: str, update: Prefs, *, from_device: str | None = None) -> Prefs:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            merged = self.store.prefs.get(wearer).merged(update)
            self.store.prefs.set(wearer, merged, now)
        self.event("pref_changed", wearer=wearer, counts={"pace_ms": merged.pace_ms, "from_device": int(from_device is not None)})
        self.devices.broadcast(wearer, PrefSet(prefs=merged.to_wire()), exclude=[from_device] if from_device else ())
        return merged.to_wire()

    # --- devices and senders (admin) ----------------------------------------

    def list_devices(self, wearer: str) -> list[DeviceView]:
        return [
            DeviceView(device=d.id, name=d.name, profile=d.profile, primary=d.primary,
                       connected=self.devices.is_connected(d.id),
                       last_seen=to_datetime(d.last_seen) if d.last_seen else None)
            for d in self.store.devices.list(wearer)
        ]

    def enroll_code(self, wearer: str) -> EnrollCodeResponse:
        now = self.clock.now()
        code = new_enroll_code()
        expires = now + self.settings.enroll_code_ttl_s
        with self.store.tx(immediate=True):
            self.store.enroll_codes.insert(hash_secret(code), wearer, expires, now)
        self.event("enroll_code", wearer=wearer)
        return EnrollCodeResponse(code=code, expires=to_datetime(expires))

    def enroll(self, body: EnrollBody) -> EnrollResponse | Refusal:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            wearer = self.store.enroll_codes.consume(body.code, now)
            if wearer is None:
                self.event("enroll_refused", reason=Reason.unauthorized)
                return Refusal(Reason.unauthorized, "unknown or expired enrollment code")
            count = self.store.devices.count(wearer)
            key = new_token()
            device = Device(id=new_id("d"), wearer=wearer, name=body.name, profile=body.profile,
                            primary=count == 0, order=count, key_hash=hash_secret(key), created=now)
            self.store.devices.insert(device)
        self.event("enrolled", wearer=wearer, counts={"devices": count + 1})
        return EnrollResponse(device=device.id, device_key=key)

    def create_sender(self, wearer: str, body: CreateSender) -> SenderView:
        now = self.clock.now()
        token = new_token()
        sender = Sender(id=new_id("s"), wearer=wearer, label=body.label, token_hash=hash_secret(token),
                        scopes=frozenset(body.scopes), rate_per_min=body.rate_per_min, created=now)
        with self.store.tx(immediate=True):
            self.store.senders.insert(sender)
        self.event("sender_created", wearer=wearer)
        return SenderView(id=sender.id, label=sender.label, scopes=sorted(sender.scopes),  # type: ignore[arg-type]
                          rate_per_min=sender.rate_per_min, created=to_datetime(now), token=token)

    def list_senders(self, wearer: str) -> list[SenderView]:
        return [SenderView(id=s.id, label=s.label, scopes=sorted(s.scopes), rate_per_min=s.rate_per_min,  # type: ignore[arg-type]
                           created=to_datetime(s.created)) for s in self.store.senders.list(wearer)]

    def list_replies(self, wearer: str, *, undelivered_only: bool = False, limit: int = 100) -> list[ReplyView]:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            rows = self.store.replies.list(wearer, undelivered_only=undelivered_only, limit=limit)
            self.store.replies.mark_delivered([r["id"] for r in rows if r["delivered"] is None], now)
        return [ReplyView(id=r["id"], words=r["words"], in_reply_to=r["in_reply_to"], created=to_datetime(r["created"]))
                for r in rows]

    # --- health -------------------------------------------------------------

    def health(self) -> Health:
        return Health(
            status="ok", version=ziv.__version__, spec_version=spec.spec_version(), wire_version=WIRE_VERSION,
            devices_connected=self.devices.count(), outbox=self.store.outbox.counts(),
            schedule_pending=self.store.schedule.count(),
            caps={"outbox": self.settings.outbox_cap, "schedule": self.settings.schedule_cap,
                  "budget_ms": self.settings.budget_ms, "device_capacity": self.settings.device_capacity,
                  "max_body_bytes": self.settings.max_body_bytes},
            compose=self.composer.health(),
        )

    # --- devices (socket side) ----------------------------------------------

    def device_hello(self, conn: DeviceConn, hello: Hello) -> HelloAck:
        now = self.clock.now()
        device = conn.device
        wearer = device.wearer
        held = set(hello.held)
        with self.store.tx(immediate=True):
            self.store.devices.touch(device.id, now)
            prefs = self.store.prefs.get(wearer)
            before = self.store.outbox.active(wearer)
            entries = outbox.forgive(before, device.id)
            entries, fx = outbox.acknowledge_hello(entries, device.id, hello.last_acked, now)
            self.devices.connect(conn)
            entries, fx2 = outbox.assign(entries, self._slots(wearer), now)
            self.store.outbox.save_changed(before, entries)
            self.store.events.append(now, "device_hello", wearer=wearer,
                                     counts={"held": len(held), "spec_version": hello.spec_version,
                                             "spec_match": int(hello.spec_version == spec.spec_version())})
        resend = [e.utterance for e in entries
                  if e.device == device.id and e.state in (State.sent, State.playing) and e.id not in held]
        # frames for this device ride in the ack's resend list, not as separate opens
        self.apply(f for f in fx + fx2 if not (isinstance(f, SendOpen) and f.device == device.id))
        # ids the device still holds that it should not play
        by_id = {e.id: e for e in entries}
        for hid in hello.held:
            e = by_id.get(hid)
            if e is None:
                e = self.store.outbox.get(hid)
            if e is None or e.wearer != wearer:
                continue
            if not (e.active and e.device == device.id):
                conn.offer(UtteranceCancel(id=hid, reason=e.reason or Reason.failover))
        return HelloAck(wearer=wearer, device=device.id, spec_version=spec.spec_version(),
                        prefs=prefs.to_wire(), resend=resend[:64])

    def device_gone(self, conn: DeviceConn) -> None:
        if not self.devices.disconnect(conn):
            return  # a newer socket for this device took over
        now = self.clock.now()
        with self.store.tx(immediate=True):
            before = self.store.outbox.by_device(conn.id)
            after, fx = outbox.on_device_gone(before, conn.id, now)
            self.store.outbox.save_changed(before, after)
        self.event("device_bye", wearer=conn.wearer, counts={"frames_sent": conn.sent_frames})
        self.apply(fx)
        if fx:
            self._assign(conn.wearer)

    def device_frame(self, conn: DeviceConn, frame) -> ProtocolError | Pong | None:
        """One up-frame after hello. Returns a frame to send back, or None."""
        now = self.clock.now()
        if isinstance(frame, Ping):
            return Pong()
        if isinstance(frame, Hello):
            return ProtocolError(reason=Reason.bad_request, detail="hello already received")
        if isinstance(frame, Progress):
            return self._transition(conn, frame.id, lambda e: outbox.on_progress(e, conn.id, frame.phase, now))
        if isinstance(frame, Played):
            played_ms = max(0, frame.closed_ms - frame.started_ms)
            return self._transition(conn, frame.id, lambda e: outbox.on_played(e, conn.id, now, played_ms))
        if isinstance(frame, Nack):
            return self._transition(conn, frame.id, lambda e: outbox.on_nack(e, conn.id, frame.reason, now))
        if isinstance(frame, InputText):
            with self.store.tx(immediate=True):
                self.store.replies.insert(conn.wearer, conn.id, frame.in_reply_to, frame.words, now)
            self.event("reply", wearer=conn.wearer, counts={"words": len(frame.words),
                                                           "addressed": int(frame.in_reply_to is not None)})
            return None
        if isinstance(frame, Control):
            self.event("control", wearer=conn.wearer, detail=frame.action)
            if frame.action == "advance":
                self._assign(conn.wearer)
            return None
        if isinstance(frame, PrefChanged):
            prefs = self.set_prefs(conn.wearer, frame.prefs, from_device=conn.id)
            conn.pace_ms = prefs.pace_ms
            return None
        return ProtocolError(reason=Reason.bad_request, detail="unknown frame")

    def _transition(self, conn: DeviceConn, id: str,
                    fn: Callable[[OutboxEntry], tuple[OutboxEntry, list[Effect]]]) -> None:
        with self.store.tx(immediate=True):
            e = self.store.outbox.get(id)
            if e is None or e.wearer != conn.wearer:
                self.event("unknown_utterance", wearer=conn.wearer)
                return None
            try:
                ne, fx = fn(e)
            except IllegalTransition as exc:
                self.event("late_frame", wearer=conn.wearer, detail=f"{exc.event} in {exc.state}")
                return None
            if ne != e:
                self.store.outbox.save(ne)
        self.apply(fx)
        if ne.state in (State.played, State.failed):
            self._assign(conn.wearer)
        return None

    # --- the scheduler's work (called by scheduler.tick) --------------------

    def fire(self, row: ScheduleEntry) -> None:
        """Turn one claimed schedule row into an outbox row through admission,
        deleting the schedule row in the same transaction."""
        now = self.clock.now()
        wearer = row.wearer
        if row.text is not None:
            n = admission.normalise(row.text, allow_lossy=True)
            words = () if isinstance(n, Refusal) else n.words
            body_pending = False
            source = Source.sender
        else:
            words, body_pending, source = (), True, self.composer.source
        if not words and not body_pending:
            self.event("schedule_refused", wearer=wearer, reason=Reason.bad_request)
            self.store.schedule.delete(row.id or 0)
            return
        utt = schedule.build_utterance(row, id=self._new_id(now), words=words, body_pending=body_pending,
                                       source=source, sender=SCHEDULE_SENDER)
        prefs = self.store.prefs.get(wearer)
        profile = self._profile_for(wearer)
        measured = admission.check_budget(utt, profile, prefs.pace_ms, self.settings.budget_ms)
        if isinstance(measured, Refusal):
            self._refused(wearer, measured, "schedule_fire")
            with self.store.tx(immediate=True):
                self.store.schedule.delete(row.id or 0)  # it will never fit; keeping it would retry forever
            return
        entry = OutboxEntry(utterance=utt, state=State.pending, created=now, updated=now,
                            duration_ms=measured, budget_ms=self.settings.budget_ms)
        with self.store.tx(immediate=True):
            active = self.store.outbox.active(wearer)
            result = outbox.admit(active, entry, self.settings.outbox_cap)
            if isinstance(result, Refusal):
                # at the cap: keep the promise, retry after the lease
                self._refused(wearer, result, "schedule_deferred")
                return
            entry, fx = result
            if not self.store.schedule.fire(row.id or 0, entry):
                return  # already fired by another claim
            before = active + [entry]
            after, fx2 = outbox.assign(before, self._slots(wearer), now)
            self.store.outbox.save_changed(before, after)
        self.apply(fx + fx2)
        self.event("schedule_fired", wearer=wearer, counts={"composed": int(body_pending)})
        if body_pending:
            self._spawn_compose(entry.id, row.intent or "", wearer, row.kind, profile, prefs.pace_ms)

    def _spawn_compose(self, entry_id: str, intent: str, wearer: str, kind: Kind, profile: Profile, pace_ms: int) -> None:
        task = asyncio.get_running_loop().create_task(self._compose(entry_id, intent, wearer, kind, profile, pace_ms))
        self._compose_tasks[entry_id] = task
        task.add_done_callback(lambda t, eid=entry_id: self._compose_tasks.pop(eid, None))

    async def _compose(self, entry_id: str, intent: str, wearer: str, kind: Kind, profile: Profile, pace_ms: int) -> None:
        try:
            words = await self.composer.compose(intent, self.settings.budget_ms, profile=profile, pace_ms=pace_ms, kind=kind)
        except asyncio.CancelledError:
            raise
        except ComposeError as exc:
            self.event("compose", wearer=wearer, reason=exc.reason, counts={"ok": 0}, detail=exc.detail[:80])
            self.compose_failed(entry_id, exc.reason)
            return
        except Exception as exc:  # the composer is an adapter; a bug there must not kill the loop
            self.event("compose", wearer=wearer, reason=Reason.compose_failed, counts={"ok": 0},
                       detail=type(exc).__name__)
            self.compose_failed(entry_id, Reason.compose_failed)
            return
        self.event("compose", wearer=wearer, counts={"ok": 1, "words": len(words)})
        self.compose_done(entry_id, words, self.composer.source)

    def compose_done(self, entry_id: str, words: Sequence[str], source: Source) -> None:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            e = self.store.outbox.get(entry_id)
            if e is None or e.terminal:
                self.event("compose_late", wearer=e.wearer if e else None)
                return
            prefs = self.store.prefs.get(e.wearer)
            probe = e.utterance.model_copy(update={"words": list(words), "body_pending": False})
            duration = admission.measure(probe, self._profile_for(e.wearer, e.device), prefs.pace_ms)
            try:
                ne, fx = outbox.on_body(e, words, source, duration, now)
            except IllegalTransition as exc:
                self.event("late_frame", wearer=e.wearer, detail=f"{exc.event} in {exc.state}")
                return
            self.store.outbox.save(ne)
        self.apply(fx)

    def compose_failed(self, entry_id: str, reason: Reason) -> None:
        now = self.clock.now()
        with self.store.tx(immediate=True):
            e = self.store.outbox.get(entry_id)
            if e is None or e.terminal:
                return
            try:
                ne, fx = outbox.on_compose_failed(e, reason, now)
            except IllegalTransition:
                return
            self.store.outbox.save(ne)
        self.apply(fx)
        self._assign(e.wearer)

    def expire(self, now: float) -> None:
        effects: list[Effect] = []
        with self.store.tx(immediate=True):
            for wearer in self.store.outbox.wearers_with_active():
                prefs = self.store.prefs.get(wearer)
                before = self.store.outbox.active(wearer)
                after, fx = outbox.on_expiry(before, now, prefs.late)
                self.store.outbox.save_changed(before, after)
                effects.extend(fx)
        self.apply(effects)

    def failover(self, now: float) -> list[str]:
        with self.store.tx(immediate=True):
            before = self.store.outbox.active_all()
            after, fx = outbox.failover(before, now, self.settings.handoff_window_s)
            self.store.outbox.save_changed(before, after)
        self.apply(fx)
        touched = sorted({a.wearer for a, b in zip(after, before) if a != b})
        for wearer in touched:
            self._assign(wearer)
        return touched

    def body_timeouts(self, now: float) -> int:
        """Fail body_pending entries whose body never came within the timeout."""
        stale = [e for e in self.store.outbox.active_all()
                 if e.body_pending and now - e.created >= self.settings.body_timeout_s]
        for e in stale:
            task = self._compose_tasks.pop(e.id, None)
            if task is not None:
                task.cancel()
            self.compose_failed(e.id, Reason.body_timeout)
        return len(stale)

    def prune(self, now: float) -> dict[str, int]:
        self._last_prune = now
        return self.store.prune(now, self.retention)

    def prune_due(self, now: float) -> bool:
        return self._last_prune is None or now - self._last_prune >= self.settings.prune_interval_s

    async def drain(self) -> None:
        """Wait for outstanding compose tasks (tests; shutdown)."""
        tasks = list(self._compose_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def tick(self, now: float | None = None) -> None:
        from . import scheduler

        await scheduler.tick(self, self.clock.now() if now is None else now)
