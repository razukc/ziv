"""ziv.core.admission — text to words, and words to a time budget.

``normalise`` turns what a sender typed into the exact lower-case ``a``–``z``
words the wearer will feel, deterministically: digits become English number
words, punctuation is dropped, and anything left without a cell is refused by
name unless the sender opted into lossy transliteration. ``check_budget``
measures the utterance with the reference renderer and refuses anything over
the budget, stating both numbers. Nothing here is ever sliced.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ziv.wire import MAX_WORDS, Profile, Reason, Utterance

from . import spec
from .model import Refusal

WORD_MAX_LETTERS = 32  # mirrors the ``Word`` pattern in ziv.wire

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n: int) -> list[str]:
    """English words for ``0 <= n <= 9999``: ``twenty one``, ``one hundred five``."""
    if n < 0 or n > 9999:
        raise ValueError("number_words covers 0..9999")
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        return [_TENS[tens]] + ([_ONES[ones]] if ones else [])
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_ONES[hundreds], "hundred"] + (number_words(rest) if rest else [])
    thousands, rest = divmod(n, 1000)
    return [_ONES[thousands], "thousand"] + (number_words(rest) if rest else [])


def digits_to_words(digits: str) -> list[str]:
    """One run of digits as words. Up to four digits read as a number; a run with
    a leading zero or longer than four reads digit by digit, so ``007`` is
    ``zero zero seven`` and a phone number is never a quantity."""
    if len(digits) > 4 or (len(digits) > 1 and digits[0] == "0"):
        return [_ONES[int(d)] for d in digits]
    return number_words(int(digits))


_DIGIT_RUN = re.compile(r"\d+")
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}\b)")


def spoken_numbers(text: str) -> str:
    """Digits as words, spaced from glued letters: ``9am`` → ``nine am``."""
    text = _THOUSANDS_COMMA.sub("", text)

    def spell(m: re.Match[str]) -> str:
        words = " ".join(digits_to_words(m.group()))
        before = m.start() > 0 and text[m.start() - 1].isalpha()
        after = m.end() < len(text) and text[m.end()].isalpha()
        return (" " if before else "") + words + (" " if after else "")

    return _DIGIT_RUN.sub(spell, text)


_APOSTROPHES = "'’ʼ"
_PUNCT = set("!\"#$%&()*+,-./:;<=>?@[\\]^_`{|}~–—…«»“”‘")


@dataclass(frozen=True, slots=True)
class Normalised:
    words: tuple[str, ...]
    lossy: bool = False            # characters were dropped under allow_lossy
    dropped: tuple[str, ...] = ()  # which ones (for the sender's response only)


def normalise(text: str, *, allow_lossy: bool = False) -> Normalised | Refusal:
    """Sender text → the words that will be felt, or a refusal naming why not."""
    lowered = spoken_numbers(text.lower())
    kept: list[str] = []
    offending: list[str] = []
    for ch in lowered:
        if "a" <= ch <= "z" or ch.isspace():
            kept.append(ch)
        elif ch in _APOSTROPHES:
            continue  # don't → dont
        elif ch in _PUNCT:
            kept.append(" ")
        elif allow_lossy:
            # lossy transliteration: strip accents (é → e), drop the rest
            base = unicodedata.normalize("NFKD", ch)
            letters = [c for c in base if "a" <= c <= "z"]
            if letters:
                kept.extend(letters)
            else:
                kept.append(" ")
            offending.append(ch)
        else:
            offending.append(ch)
    if offending and not allow_lossy:
        chars = sorted(set(offending))
        return Refusal(
            Reason.unencodable,
            "characters with no braille cell: " + " ".join(chars) + " (set allow_lossy to drop them)",
            {"characters": chars},
        )
    words = tuple(w for w in "".join(kept).split() if w)
    if not words:
        return Refusal(Reason.bad_request, "no words to play", {"words": 0})
    too_long = [w for w in words if len(w) > WORD_MAX_LETTERS]
    if too_long:
        return Refusal(
            Reason.unencodable,
            f"a word longer than {WORD_MAX_LETTERS} letters cannot be played whole",
            {"max_letters": WORD_MAX_LETTERS, "letters": len(too_long[0])},
        )
    if len(words) > MAX_WORDS:
        return Refusal(
            Reason.bad_request,
            f"{len(words)} words; the wire carries at most {MAX_WORDS}",
            {"words": len(words), "max_words": MAX_WORDS},
        )
    return Normalised(words, lossy=bool(offending), dropped=tuple(sorted(set(offending))))


def measure(utt: Utterance, profile: Profile, pace_ms: int) -> int:
    """How long ``utt`` takes on ``profile`` at ``pace_ms`` — the reference renderer's answer."""
    return spec.duration_ms(utt, profile, pace_ms)


def check_budget(utt: Utterance, profile: Profile, pace_ms: int, budget_ms: int) -> int | Refusal:
    """The utterance's duration, or an ``over_budget`` refusal stating both numbers."""
    duration = measure(utt, profile, pace_ms)
    if duration > budget_ms:
        return Refusal(
            Reason.over_budget,
            f"{duration} ms to play; the budget is {budget_ms} ms",
            {"duration_ms": duration, "budget_ms": budget_ms},
        )
    return duration
