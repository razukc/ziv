"""ziv.wire — the wire contract.

Everything that crosses a process boundary is defined here and nowhere else:
the utterance (the unit a device owns whole), the device frames (both
directions on the WebSocket), and the sender-facing HTTP bodies. The console,
the web client and the firmware's decoder tests build against the JSON Schema
this module emits (``python -m ziv.wire schema/``), so a field added here is
a field everywhere, and a field added anywhere else is a bug.

Rules the models enforce:

* ``extra="forbid"`` on every model — an unknown field is a refusal, not a
  silent pass.
* Hard sizes on every string and list. The relay must never accept a body it
  cannot bound.
* Words are lower-case ``a``–``z`` only. Normalisation (digits to words,
  punctuation dropped, unencodable characters refused) happens in the relay
  before a word is ever constructed.
* No durations anywhere. Timing is resolved from the spec on the device and
  by the reference renderer; the wire carries intent, not milliseconds.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

WIRE_VERSION = 1

# --- vocabularies -----------------------------------------------------------


class Kind(StrEnum):
    """What sort of event an utterance is. Selects the arrival cue and the
    tail after the name mark; the mapping lives in the timing spec."""

    message = "message"
    reminder = "reminder"
    error = "error"
    system = "system"


class Profile(StrEnum):
    """How a device encodes a cell. The reference renderer knows every one."""

    six_actuator = "six_actuator"      # the band: raised dots driven together
    single_actuator = "single_actuator"  # a phone: six time slots per cell


class State(StrEnum):
    """Outbox states (docs/ARCHITECTURE.md §4.1)."""

    pending = "pending"
    sent = "sent"
    playing = "playing"
    played = "played"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"


class Source(StrEnum):
    """How the words were produced. ``live`` only when a model actually ran."""

    sender = "sender"   # typed by a sender, normalised by the relay
    echo = "echo"       # an intent played verbatim because no model ran
    live = "live"       # a model wrote the line


class Phase(StrEnum):
    cue = "cue"
    working = "working"
    word = "word"
    close = "close"


class Advance(StrEnum):
    """Who starts the next utterance after a close: the device, or the wearer."""

    auto = "auto"
    tap = "tap"


class Late(StrEnum):
    """What to do with an utterance that passed ``expires`` before playing."""

    drop = "drop"
    play = "play"


class Reason(StrEnum):
    """Every refusal, nack and cancellation names one of these."""

    queue_full = "queue_full"
    over_budget = "over_budget"
    unencodable = "unencodable"
    expired = "expired"
    spec_mismatch = "spec_mismatch"
    body_timeout = "body_timeout"
    hidden = "hidden"
    muted = "muted"
    device_gone = "device_gone"
    failover = "failover"
    compose_failed = "compose_failed"
    cancelled_by_sender = "cancelled_by_sender"
    cancelled_by_wearer = "cancelled_by_wearer"
    unauthorized = "unauthorized"
    bad_request = "bad_request"
    rate_limited = "rate_limited"
    not_found = "not_found"
    conflict = "conflict"


# --- scalars ----------------------------------------------------------------

Word = Annotated[str, Field(pattern=r"^[a-z]{1,32}$")]
UtteranceId = Annotated[str, Field(pattern=r"^[0-9A-Za-z_-]{8,64}$")]
WearerId = Annotated[str, Field(pattern=r"^[0-9A-Za-z_-]{1,64}$")]
DeviceId = Annotated[str, Field(pattern=r"^[0-9A-Za-z_-]{1,64}$")]
SenderId = Annotated[str, Field(pattern=r"^[0-9A-Za-z_.-]{1,64}$")]
PatternId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
Label = Annotated[str, Field(max_length=40)]
MAX_WORDS = 64
MAX_TEXT = 500


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


# --- the utterance ----------------------------------------------------------


class Prefix(Strict):
    """The name mark and the kind's tail, played before unsolicited content."""

    mark: Annotated[str, Field(pattern=r"^[a-z]{1,8}$")]
    tail: PatternId


class From(Strict):
    sender: SenderId
    label: Label | None = None


class Prefs(Strict):
    """The wearer's preferences, as they travel on the wire. The relay clamps
    ``pace_ms`` into the spec's envelope; the device applies it."""

    pace_ms: Annotated[int, Field(ge=100, le=2000)] | None = None
    advance: Advance | None = None
    late: Late | None = None
    history: bool | None = None


class Utterance(Strict):
    """The unit the wearer feels (docs/ARCHITECTURE.md §2)."""

    v: Literal[1] = 1
    id: UtteranceId
    wearer: WearerId
    kind: Kind
    from_: From = Field(alias="from")
    prefix: Prefix | None = None
    words: Annotated[list[Word], Field(max_length=MAX_WORDS)] = Field(default_factory=list)
    body_pending: bool = False
    source: Source = Source.sender
    not_before: datetime | None = None
    expires: datetime | None = None
    spec_version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _words_or_pending(self) -> "Utterance":
        if not self.body_pending and not self.words:
            raise ValueError("an utterance needs words unless body_pending is true")
        if self.not_before and self.expires and self.expires <= self.not_before:
            raise ValueError("expires must be after not_before")
        return self


# --- device frames: relay -> device ----------------------------------------


class HelloAck(Strict):
    type: Literal["hello.ack"] = "hello.ack"
    v: Literal[1] = 1
    wearer: WearerId
    device: DeviceId
    spec_version: int
    prefs: Prefs
    resend: Annotated[list[Utterance], Field(max_length=64)] = Field(default_factory=list)


class UtteranceOpen(Strict):
    type: Literal["utterance.open"] = "utterance.open"
    utterance: Utterance


class UtteranceBody(Strict):
    """The words for a ``body_pending`` utterance — or the reason there are none."""

    type: Literal["utterance.body"] = "utterance.body"
    id: UtteranceId
    words: Annotated[list[Word], Field(max_length=MAX_WORDS)] = Field(default_factory=list)
    source: Source = Source.live
    error: Reason | None = None

    @model_validator(mode="after")
    def _words_or_error(self) -> "UtteranceBody":
        if bool(self.words) == bool(self.error):
            raise ValueError("a body carries words or an error, exactly one")
        return self


class UtteranceCancel(Strict):
    type: Literal["utterance.cancel"] = "utterance.cancel"
    id: UtteranceId
    reason: Reason


class PrefSet(Strict):
    type: Literal["pref.set"] = "pref.set"
    prefs: Prefs


class Pong(Strict):
    type: Literal["pong"] = "pong"


class ProtocolError(Strict):
    """A frame the relay could not accept. Never carries message text."""

    type: Literal["error"] = "error"
    reason: Reason
    detail: Annotated[str, Field(max_length=200)] = ""


DownFrame = Annotated[
    Union[HelloAck, UtteranceOpen, UtteranceBody, UtteranceCancel, PrefSet, Pong, ProtocolError],
    Field(discriminator="type"),
]


# --- device frames: device -> relay ----------------------------------------


class Hello(Strict):
    """The first frame on a device socket. Carries the credential, so no key
    ever appears in a URL or an access log."""

    type: Literal["hello"] = "hello"
    v: Literal[1] = 1
    device_key: Annotated[str, Field(min_length=16, max_length=128)]
    profile: Profile
    spec_version: Annotated[int, Field(ge=1)]
    pace_ms: Annotated[int, Field(ge=100, le=2000)] | None = None
    last_acked: UtteranceId | None = None
    held: Annotated[list[UtteranceId], Field(max_length=64)] = Field(default_factory=list)


class Progress(Strict):
    type: Literal["progress"] = "progress"
    id: UtteranceId
    phase: Phase
    word_index: Annotated[int, Field(ge=0, le=MAX_WORDS)] | None = None


class Played(Strict):
    """The close finished on the actuator. Timestamps are the device's own
    monotonic clock in milliseconds; the relay uses the difference only."""

    type: Literal["played"] = "played"
    id: UtteranceId
    started_ms: Annotated[int, Field(ge=0)]
    closed_ms: Annotated[int, Field(ge=0)]


class Nack(Strict):
    type: Literal["nack"] = "nack"
    id: UtteranceId
    reason: Reason


class InputText(Strict):
    """Words typed on the chord keys (or the phone), as a reply or unaddressed."""

    type: Literal["input.text"] = "input.text"
    words: Annotated[list[Word], Field(min_length=1, max_length=MAX_WORDS)]
    in_reply_to: UtteranceId | None = None


class Control(Strict):
    type: Literal["control"] = "control"
    action: Literal["stop", "replay", "replay_word", "skip", "advance"]


class PrefChanged(Strict):
    type: Literal["pref.changed"] = "pref.changed"
    prefs: Prefs


class Ping(Strict):
    type: Literal["ping"] = "ping"


UpFrame = Annotated[
    Union[Hello, Progress, Played, Nack, InputText, Control, PrefChanged, Ping],
    Field(discriminator="type"),
]

down_frame_adapter: TypeAdapter = TypeAdapter(DownFrame)
up_frame_adapter: TypeAdapter = TypeAdapter(UpFrame)


# --- sender HTTP bodies -----------------------------------------------------


class SubmitUtterance(Strict):
    """``POST /utterances``. ``text`` is normalised by the relay; ``words`` skips
    normalisation for callers that already speak the alphabet."""

    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)] | None = None
    words: Annotated[list[Word], Field(min_length=1, max_length=MAX_WORDS)] | None = None
    kind: Kind = Kind.message
    label: Label | None = None
    not_before: datetime | None = None
    expires: datetime | None = None
    allow_lossy: bool = False

    @model_validator(mode="after")
    def _text_or_words(self) -> "SubmitUtterance":
        if bool(self.text) == bool(self.words):
            raise ValueError("provide text or words, exactly one")
        return self


class ComposeBody(Strict):
    """``POST /compose``: an intent the agent turns into the words (docs/ARCHITECTURE.md §4.5).

    The relay admits a ``body_pending`` utterance at once, so the device cues
    and plays the working pattern, then composes and sends ``utterance.body``.
    A caller may supply its own model credential in the ``X-Nebius-Key``
    header; it is used for that one call and never stored or logged."""

    intent: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Kind = Kind.reminder
    label: Label | None = None
    expires_after_s: Annotated[int, Field(ge=60, le=86_400)] = 3600


class UtteranceView(Strict):
    """What a sender sees about an utterance: the id, its state, the exact words
    that will be felt, and the budget it was measured against."""

    id: UtteranceId
    state: State
    kind: Kind
    words: list[Word]
    source: Source
    duration_ms: int
    budget_ms: int
    device: DeviceId | None = None
    reason: Reason | None = None
    created: datetime
    updated: datetime
    lossy: bool = False      # normalisation dropped characters the sender allowed to drop


class ScheduleBody(Strict):
    """``POST /schedule``. ``text`` plays as written; ``intent`` is composed by the
    agent when it fires."""

    fire_at: datetime
    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)] | None = None
    intent: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    kind: Kind = Kind.reminder
    label: Label | None = None
    expires_after_s: Annotated[int, Field(ge=60, le=86_400)] = 3600

    @model_validator(mode="after")
    def _text_or_intent(self) -> "ScheduleBody":
        if bool(self.text) == bool(self.intent):
            raise ValueError("provide text or intent, exactly one")
        return self


class ScheduleView(Strict):
    id: Annotated[int, Field(ge=1)]
    fire_at: datetime
    kind: Kind
    composed: bool          # true when an intent will be composed at fire time
    label: Label | None = None


class EnrollBody(Strict):
    """``POST /devices/enroll``: a short-lived code from the console for a key."""

    code: Annotated[str, Field(pattern=r"^[0-9A-Z]{6,12}$")]
    profile: Profile
    name: Label


class EnrollResponse(Strict):
    device: DeviceId
    device_key: str      # shown exactly once; the relay stores a hash


class EnrollCodeResponse(Strict):
    """``POST /devices/enroll-code`` (admin): a short-lived code to exchange once."""

    code: Annotated[str, Field(pattern=r"^[0-9A-Z]{6,12}$")]
    expires: datetime


class CreateSender(Strict):
    """``POST /senders`` (admin): mint a scoped bearer token for one sender."""

    label: Label
    scopes: Annotated[list[Literal["send", "read", "admin"]], Field(min_length=1, max_length=3)] = Field(
        default_factory=lambda: ["send", "read"]
    )
    rate_per_min: Annotated[int, Field(ge=1, le=6000)] = 60


class SenderView(Strict):
    id: SenderId
    label: Label
    scopes: list[Literal["send", "read", "admin"]]
    rate_per_min: int
    created: datetime
    token: str | None = None   # shown exactly once, on creation; the relay stores a hash


class ReplyView(Strict):
    """Words the wearer typed on the chord keys, for the sender to read."""

    id: Annotated[int, Field(ge=1)]
    words: list[Word]
    in_reply_to: UtteranceId | None = None
    created: datetime


class DeviceView(Strict):
    device: DeviceId
    name: Label
    profile: Profile
    primary: bool
    connected: bool
    last_seen: datetime | None = None


class Health(Strict):
    """Counts only. Never a word of content."""

    status: Literal["ok"]
    version: str
    spec_version: int
    wire_version: int
    devices_connected: int
    outbox: dict[str, int]   # state -> count
    schedule_pending: int
    caps: dict[str, int]
    compose: dict[str, object] | None = None


# --- schema export ----------------------------------------------------------

SCHEMAS: dict[str, TypeAdapter] = {
    "utterance": TypeAdapter(Utterance),
    "device-frames-down": down_frame_adapter,
    "device-frames-up": up_frame_adapter,
    "http-submit-utterance": TypeAdapter(SubmitUtterance),
    "http-compose": TypeAdapter(ComposeBody),
    "http-utterance-view": TypeAdapter(UtteranceView),
    "http-schedule": TypeAdapter(ScheduleBody),
    "http-schedule-view": TypeAdapter(ScheduleView),
    "http-prefs": TypeAdapter(Prefs),
    "http-enroll": TypeAdapter(EnrollBody),
    "http-enroll-response": TypeAdapter(EnrollResponse),
    "http-enroll-code-response": TypeAdapter(EnrollCodeResponse),
    "http-create-sender": TypeAdapter(CreateSender),
    "http-sender-view": TypeAdapter(SenderView),
    "http-reply-view": TypeAdapter(ReplyView),
    "http-device-view": TypeAdapter(DeviceView),
    "http-health": TypeAdapter(Health),
}


def dump_schemas(out_dir: str) -> list[str]:
    """Write one JSON Schema file per contract into ``out_dir``; return the paths."""
    import json
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, adapter in SCHEMAS.items():
        path = out / f"{name}.json"
        schema = adapter.json_schema(by_alias=True)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$comment"] = "GENERATED from ziv/wire.py — do not edit; run: python -m ziv.wire schema/"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path))
    return written


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "schema"
    for p in dump_schemas(target):
        print("wrote", p)
