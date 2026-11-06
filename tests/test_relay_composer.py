"""The composers: echo, fake, and the model provider behind a mock transport."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ziv.core import spec
from ziv.wire import Reason
from ziv.relay.composer import ComposeError, EchoComposer, FakeComposer, NebiusComposer, measure_words
from ziv.wire import Kind, Profile

PACE = spec.pace_envelope()[2]
KEY = "sk-byok-secret-0123456789"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def provider(lines, status=200, content_none=False):
    """A mock chat/completions endpoint that answers the scripted lines in turn."""
    seen = {"requests": [], "auth": []}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["requests"].append(json.loads(request.content))
        seen["auth"].append(request.headers.get("authorization"))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": f"key {KEY} rejected"}})
        content = None if content_none else lines[min(len(seen["requests"]) - 1, len(lines) - 1)]
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler), seen


def composer(transport, api_key="configured-key-000"):
    return NebiusComposer(api_key=api_key, base_url="https://example.invalid/v1", model="m", transport=transport)


def test_first_answer_fits():
    t, seen = provider(["Take meds at 9"])
    c = composer(t)
    words = run(c.compose("take the meds", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    assert words == ["take", "meds", "at", "nine"]
    assert len(seen["requests"]) == 1
    req = seen["requests"][0]
    assert req["max_tokens"] == 64 and req["temperature"] == 0 and req["chat_template_kwargs"] == {"enable_thinking": False}
    assert req["messages"][0]["role"] == "system" and "take the meds" in req["messages"][1]["content"]
    h = c.health()
    assert h["attempts"] == 1 and h["ok"] == 1 and h["last_status"] == "ok" and h["last_calls"] == 1


def test_corrective_retry_names_the_defect_then_two_words():
    long = "remember to take the morning medication with water now please"
    t, seen = provider([long, long, "meds now"])
    c = composer(t)
    words = run(c.compose("meds", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    assert words == ["meds", "now"] and len(seen["requests"]) == 3
    correction = seen["requests"][1]["messages"][1]["content"]
    assert "cannot play whole" in correction and "ms" in correction and "15000" in correction
    assert "two most useful words" in seen["requests"][2]["messages"][1]["content"]
    assert c.health()["last_calls"] == 3


def test_three_misses_fail_loudly_and_content_free():
    long = "remember to take the morning medication with water now please"
    t, seen = provider([long])
    c = composer(t)
    with pytest.raises(ComposeError) as exc:
        run(c.compose("meds", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    assert exc.value.reason == "compose_failed" and "remember" not in exc.value.detail
    assert c.health()["last_error_kind"] == "over_budget" and c.health()["failed"] == 1


def test_provider_errors_are_kinds_not_text_and_keys_are_scrubbed():
    t, seen = provider([], status=401)
    c = composer(t, api_key=None)
    with pytest.raises(ComposeError) as exc:
        run(c.compose("meds", 15_000, profile=Profile.six_actuator, pace_ms=PACE, api_key=KEY))
    assert exc.value.detail == "provider http_401" and KEY not in exc.value.detail
    assert seen["auth"] == [f"Bearer {KEY}"]          # the supplied key was used for the call ...
    assert c._api_key is None                            # ... and never kept
    assert KEY not in json.dumps(c.health())
    t, _ = provider([""], content_none=True)
    with pytest.raises(ComposeError) as exc:
        run(composer(t).compose("x", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    assert exc.value.detail == "provider empty_content"


def test_no_key_is_a_loud_failure():
    c = composer(httpx.MockTransport(lambda r: httpx.Response(500)), api_key=None)
    with pytest.raises(ComposeError):
        run(c.compose("x", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    assert c.health()["last_error_kind"] == "no_key" and c.health()["configured"] is False


def test_transport_failure_is_a_kind():
    def boom(request):
        raise httpx.ConnectError("refused")

    c = composer(httpx.MockTransport(boom))
    with pytest.raises(ComposeError) as exc:
        run(c.compose("x", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    assert exc.value.detail == "provider transport_connecterror"


def test_echo_plays_the_whole_intent_or_drops_function_words_or_refuses():
    """The echo path never cuts content: "meds at nine" must not become "meds at"."""
    e = EchoComposer()
    assert run(e.compose("take meds at 9", 15_000, profile=Profile.six_actuator, pace_ms=PACE)) == ["take", "meds", "at", "nine"]
    trimmed = measure_words(["take", "meds", "nine"], kind=Kind.reminder, profile=Profile.six_actuator, pace_ms=PACE)
    assert run(e.compose("take meds at nine", trimmed, profile=Profile.six_actuator, pace_ms=PACE)) == ["take", "meds", "nine"]
    tight = measure_words(["take", "meds"], kind=Kind.reminder, profile=Profile.six_actuator, pace_ms=PACE)
    with pytest.raises(ComposeError) as exc:
        run(e.compose("take meds at nine", tight, profile=Profile.six_actuator, pace_ms=PACE))
    assert exc.value.reason == Reason.over_budget
    assert e.fit("take meds at nine", tight, profile=Profile.six_actuator, pace_ms=PACE) is None
    assert e.fit("take meds at nine", trimmed, profile=Profile.six_actuator, pace_ms=PACE) == ("take", "meds", "nine")
    with pytest.raises(ComposeError):
        run(e.compose("!!!", 15_000, profile=Profile.six_actuator, pace_ms=PACE))
    with pytest.raises(ComposeError):
        run(e.compose("supercalifragilistic", 100, profile=Profile.six_actuator, pace_ms=PACE))
    assert e.health()["source"] == "echo" and e.health()["attempts"] == 5


def test_fake_composer_is_scripted():
    f = FakeComposer([["a"], ComposeError()])
    assert run(f.compose("i", 1, profile=Profile.six_actuator, pace_ms=PACE)) == ["a"]
    with pytest.raises(ComposeError):
        run(f.compose("i", 1, profile=Profile.six_actuator, pace_ms=PACE))
    with pytest.raises(ComposeError):
        run(f.compose("i", 1, profile=Profile.six_actuator, pace_ms=PACE))   # unscripted
    assert len(f.calls) == 3 and f.health()["failed"] == 2


def test_measure_words_is_the_reference_budget():
    from ziv.wire import Utterance

    words = ["meds", "nine"]
    utt = Utterance(id="measure-only-0000", wearer="measure", kind=Kind.reminder, **{"from": {"sender": "compose"}},
                    prefix=spec.prefix_for(Kind.reminder), words=words, spec_version=spec.spec_version())
    assert measure_words(words, kind=Kind.reminder, profile=Profile.six_actuator, pace_ms=PACE) == \
        spec.duration_ms(utt, Profile.six_actuator, PACE)
