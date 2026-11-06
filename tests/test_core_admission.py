"""Normalisation and the time budget: deterministic words, loud refusals."""
from __future__ import annotations

from hypothesis import given, strategies as st

from ziv.core import spec
from ziv.core.admission import (
    Normalised,
    check_budget,
    digits_to_words,
    normalise,
    number_words,
    spoken_numbers,
)
from ziv.core.model import Refusal
from ziv.wire import Kind, Profile, Reason, Utterance


def words_of(text, **kw):
    n = normalise(text, **kw)
    assert isinstance(n, Normalised), n
    return list(n.words)


def test_lowercase_and_punctuation_dropped():
    assert words_of("Hello, World!") == ["hello", "world"]
    assert words_of("don't stop") == ["dont", "stop"]
    assert words_of("well-known e-mail") == ["well", "known", "e", "mail"]


def test_digits_become_words_deterministically():
    assert words_of("meds at 9") == ["meds", "at", "nine"]
    assert words_of("9am") == ["nine", "am"]
    assert words_of("at 9:30") == ["at", "nine", "thirty"]
    assert words_of("room 1250") == ["room", "one", "thousand", "two", "hundred", "fifty"]
    assert words_of("1,250 pills") == ["one", "thousand", "two", "hundred", "fifty", "pills"]
    assert words_of("call 07123") == ["call", "zero", "seven", "one", "two", "three"]
    assert words_of("12345") == ["one", "two", "three", "four", "five"]
    assert words_of("x9y") == ["x", "nine", "y"]


def test_number_words_table():
    assert number_words(0) == ["zero"]
    assert number_words(21) == ["twenty", "one"]
    assert number_words(105) == ["one", "hundred", "five"]
    assert number_words(999) == ["nine", "hundred", "ninety", "nine"]
    assert number_words(2026) == ["two", "thousand", "twenty", "six"]
    assert digits_to_words("0") == ["zero"]
    assert digits_to_words("007") == ["zero", "zero", "seven"]


@given(st.integers(0, 9999))
def test_number_words_are_lowercase_letters(n):
    for w in number_words(n):
        assert w.isalpha() and w.islower()


@given(st.text(min_size=1, max_size=40))
def test_normalise_is_total_and_words_are_cells(text):
    n = normalise(text, allow_lossy=True)
    if isinstance(n, Refusal):
        assert n.reason in (Reason.bad_request, Reason.unencodable)
    else:
        for w in n.words:
            assert 1 <= len(w) <= 32 and all("a" <= c <= "z" for c in w)
    strict = normalise(text, allow_lossy=False)
    assert isinstance(strict, (Refusal, Normalised))


def test_unencodable_refused_by_name_unless_lossy():
    r = normalise("café ünd 日本")
    assert isinstance(r, Refusal) and r.reason == Reason.unencodable
    assert r.detail == {"characters": ["ü", "é", "日", "本"]} or set(r.detail["characters"]) == {"ü", "é", "日", "本"}
    n = normalise("café ünd 日本", allow_lossy=True)
    assert isinstance(n, Normalised) and n.lossy and list(n.words) == ["cafe", "und"]
    assert set(n.dropped) == {"ü", "é", "日", "本"}


def test_empty_and_overlong_refused():
    r = normalise("!!! ...")
    assert isinstance(r, Refusal) and r.reason == Reason.bad_request
    r = normalise("a" * 33)
    assert isinstance(r, Refusal) and r.reason == Reason.unencodable and r.detail["letters"] == 33
    r = normalise(" ".join(["ab"] * 65))
    assert isinstance(r, Refusal) and r.reason == Reason.bad_request and r.detail["words"] == 65


def test_spoken_numbers_leaves_text_otherwise_intact():
    assert spoken_numbers("no digits here") == "no digits here"


def _utt(words):
    return Utterance(id="budget-test-1", wearer="w", kind=Kind.message, **{"from": {"sender": "t"}},
                     prefix=spec.prefix_for(Kind.message), words=words, spec_version=spec.spec_version())


def test_budget_uses_reference_renderer_and_states_both_numbers():
    pace = spec.pace_envelope()[2]
    short = _utt(["hi"])
    d = check_budget(short, Profile.six_actuator, pace, 15_000)
    assert isinstance(d, int) and d == spec.duration_ms(short, Profile.six_actuator, pace)
    long = _utt(["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"])
    r = check_budget(long, Profile.six_actuator, pace, 15_000)
    assert isinstance(r, Refusal) and r.reason == Reason.over_budget
    assert r.detail["budget_ms"] == 15_000 and r.detail["duration_ms"] > 15_000
    assert str(r.detail["duration_ms"]) in r.message and "15000" in r.message


def test_budget_grows_with_pace():
    lo, hi, _ = spec.pace_envelope()
    u = _utt(["hello", "world"])
    assert spec.duration_ms(u, Profile.six_actuator, lo) < spec.duration_ms(u, Profile.six_actuator, hi)
