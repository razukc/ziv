"""ziv.relay.composer — ``compose(intent, budget) -> words`` (docs/ARCHITECTURE.md §4.5).

Three implementations behind one protocol: ``EchoComposer`` (the intent
itself, normalised — the path when no model is configured), ``FakeComposer``
(scripted, for tests) and ``NebiusComposer`` (an OpenAI-compatible
chat/completions call). Each converts digits to words, measures the result
with the same budget function admission uses, and fails loudly. Every attempt
is recorded content-free for health. A caller-supplied key is used for the
one call and scrubbed from anything that could be surfaced.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from ziv.core import spec
from ziv.core.admission import Refusal, normalise
from ziv.wire import Kind, Profile, Reason, Source, Utterance

MEASURE_ID = "measure-only-0000"


class ComposeError(Exception):
    """The composer could not produce words that fit. ``detail`` is content-free."""

    def __init__(self, reason: Reason = Reason.compose_failed, detail: str = "") -> None:
        super().__init__(detail or str(reason))
        self.reason = reason
        self.detail = detail


class Composer(Protocol):
    source: Source

    async def compose(
        self,
        intent: str,
        budget_ms: int,
        *,
        profile: Profile,
        pace_ms: int,
        api_key: str | None = None,
        kind: Kind = Kind.reminder,
    ) -> list[str]: ...

    def health(self) -> dict[str, object]: ...


def measure_words(words: Sequence[str], *, kind: Kind, profile: Profile, pace_ms: int) -> int:
    """How long these words take as a prefixed utterance of ``kind`` — the same
    function admission uses, on a provisional utterance."""
    utt = Utterance(
        id=MEASURE_ID,
        wearer="measure",
        kind=kind,
        **{"from": {"sender": "compose"}},
        prefix=spec.prefix_for(kind),
        words=list(words),
        spec_version=spec.spec_version(),
    )
    return spec.duration_ms(utt, profile, pace_ms)


@dataclass(frozen=True, slots=True)
class Attempt:
    status: str          # "ok" | "error"
    latency_ms: int
    calls: int           # provider calls made
    error_kind: str | None = None


class ComposeLog:
    """A bounded, content-free record of compose attempts: status, latency,
    error kind. Health reads it; nothing else does."""

    def __init__(self, source: Source, maxlen: int = 50) -> None:
        self.source = source
        self._attempts: deque[Attempt] = deque(maxlen=maxlen)
        self.total = 0
        self.ok = 0
        self.failed = 0

    def record(self, attempt: Attempt) -> None:
        self._attempts.append(attempt)
        self.total += 1
        if attempt.status == "ok":
            self.ok += 1
        else:
            self.failed += 1

    def health(self) -> dict[str, object]:
        last = self._attempts[-1] if self._attempts else None
        return {
            "source": str(self.source),
            "attempts": self.total,
            "ok": self.ok,
            "failed": self.failed,
            "last_status": last.status if last else None,
            "last_latency_ms": last.latency_ms if last else None,
            "last_error_kind": last.error_kind if last else None,
            "last_calls": last.calls if last else None,
        }


def _redact(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _fit_words(line: str) -> tuple[str, ...] | None:
    n = normalise(line, allow_lossy=True)
    return None if isinstance(n, Refusal) else n.words


#: Words the echo path may drop to make an intent fit. Content words are never
#: dropped: a reminder that loses its last word loses its time.
FUNCTION_WORDS = frozenset(
    "a an the to of for and please remember dont do my your me you at in on is are be it this that".split())


def echo_candidates(intent: str) -> list[tuple[str, ...]]:
    """What the echo path may play for ``intent``: the whole line, then the line
    without function words. Never a shorter prefix."""
    n = normalise(intent, allow_lossy=True)
    if isinstance(n, Refusal) or not n.words:
        return []
    full = tuple(n.words)
    trimmed = tuple(w for w in full if w not in FUNCTION_WORDS)
    return [full] if not trimmed or trimmed == full else [full, trimmed]


class EchoComposer:
    """No model: the intent itself, normalised. If the whole line does not fit
    the budget, function words are dropped; if it still does not fit, the
    compose fails loudly with ``over_budget`` — content is never cut."""

    source = Source.echo

    def __init__(self) -> None:
        self.log = ComposeLog(self.source)

    def fit(self, intent: str, budget_ms: int, *, profile, pace_ms, kind=Kind.reminder) -> tuple[str, ...] | None:
        """The words the echo path would play, or ``None`` when nothing honest fits.
        Used at schedule time so a sender learns now, not when the reminder fires."""
        for cand in echo_candidates(intent):
            if measure_words(list(cand), kind=kind, profile=profile, pace_ms=pace_ms) <= budget_ms:
                return cand
        return None

    async def compose(self, intent, budget_ms, *, profile, pace_ms, api_key=None, kind=Kind.reminder):
        t0 = time.monotonic()
        cands = echo_candidates(intent)
        if not cands:
            self.log.record(Attempt("error", 0, 0, "no_letters"))
            raise ComposeError(detail="the intent has no letters to play")
        d = 0
        for cand in cands:
            d = measure_words(list(cand), kind=kind, profile=profile, pace_ms=pace_ms)
            if d <= budget_ms:
                self.log.record(Attempt("ok", int((time.monotonic() - t0) * 1000), 0))
                return list(cand)
        self.log.record(Attempt("error", 0, 0, "over_budget"))
        raise ComposeError(Reason.over_budget,
                           detail=f"the intent takes {d} ms on this device; the budget is {budget_ms} ms")

    def health(self) -> dict[str, object]:
        return self.log.health()


class FakeComposer:
    """Scripted results for tests: each item is a list of words to return, or
    an exception to raise. Records every call (content allowed here — it is a
    test double)."""

    def __init__(self, results: Sequence[Sequence[str] | Exception] = (), *, source: Source = Source.live) -> None:
        self.source = source
        self.results = list(results)
        self.calls: list[dict[str, object]] = []
        self.log = ComposeLog(source)

    async def compose(self, intent, budget_ms, *, profile, pace_ms, api_key=None, kind=Kind.reminder):
        self.calls.append({"intent": intent, "budget_ms": budget_ms, "profile": profile, "pace_ms": pace_ms,
                           "api_key": api_key, "kind": kind})
        if not self.results:
            self.log.record(Attempt("error", 0, 0, "unscripted"))
            raise ComposeError(detail="no scripted result")
        item = self.results.pop(0)
        if isinstance(item, Exception):
            self.log.record(Attempt("error", 0, 1, type(item).__name__))
            raise item
        self.log.record(Attempt("ok", 0, 1))
        return list(item)

    def health(self) -> dict[str, object]:
        return self.log.health()


SYSTEM_PROMPT = (
    "You compress one reminder into the single short line a vibro-braille band plays to a "
    "deafblind wearer, letter by letter. Reply with 2 or 3 short words and nothing else. "
    "If the line you want is too long, drop whole words until what is left fits: "
    "\"remember to buy milk\" becomes \"buy milk\". Write numbers as words. Reply only with the line."
)
FIRST_PROMPT = "Write the line for this intent: {intent}"
CORRECTION_PROMPT = (
    "That line cannot play whole: {problem}. Cut it to 2 or 3 short words, dropping words - "
    "not letters, not spaces. Write numbers as words. Intent: {intent}"
)
SHORTEST_PROMPT = "Reply with only the two most useful words, nothing else. Intent: {intent}"


class ProviderError(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class NebiusComposer:
    """One OpenAI-compatible chat/completions call per attempt, three attempts
    at most: the line, a correction naming the defect, then the two most
    useful words. ``api_key`` on ``compose`` is the bring-your-own-key path:
    used for this call's requests, never stored, scrubbed from any text."""

    source = Source.live

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self._transport = transport
        self.log = ComposeLog(self.source)

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self.model)

    async def _ask(self, key: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            "max_tokens": 64,
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as client:
                resp = await client.post(
                    self.base_url + "/chat/completions", json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("transport_" + type(exc).__name__.lower()) from exc
        if resp.status_code != 200:
            raise ProviderError(f"http_{resp.status_code}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("bad_json") from exc
        if content is None:
            raise ProviderError("empty_content")  # reasoning-only answer
        lines = [ln.strip() for ln in str(content).strip().splitlines() if ln.strip()]
        line = (lines[0] if lines else "").strip('"').strip("'").strip()
        if not line:
            raise ProviderError("empty_line")
        return line

    async def compose(self, intent, budget_ms, *, profile, pace_ms, api_key=None, kind=Kind.reminder):
        key = api_key or self._api_key
        if not key:
            self.log.record(Attempt("error", 0, 0, "no_key"))
            raise ComposeError(detail="no model credential configured")
        t0 = time.monotonic()
        calls = 0

        def elapsed() -> int:
            return int((time.monotonic() - t0) * 1000)

        try:
            problem: str | None = None
            prompts = [FIRST_PROMPT, CORRECTION_PROMPT, SHORTEST_PROMPT]
            for i, template in enumerate(prompts):
                calls += 1
                line = await self._ask(key, template.format(intent=intent, problem=problem or ""))
                words = _fit_words(line)
                if not words:
                    problem = "no letter in it can be felt"
                    continue
                d = measure_words(words, kind=kind, profile=profile, pace_ms=pace_ms)
                if d <= budget_ms:
                    self.log.record(Attempt("ok", elapsed(), calls))
                    return list(words)
                problem = f"{len(words)} words take {d} ms and the band has {budget_ms} ms"
            self.log.record(Attempt("error", elapsed(), calls, "over_budget"))
            raise ComposeError(detail=f"{calls} attempts did not fit the budget")
        except ProviderError as exc:
            self.log.record(Attempt("error", elapsed(), calls, exc.kind))
            raise ComposeError(detail=_redact(f"provider {exc.kind}", key, self._api_key)) from None

    def health(self) -> dict[str, object]:
        out = self.log.health()
        out["configured"] = self.configured
        out["model"] = self.model
        return out
