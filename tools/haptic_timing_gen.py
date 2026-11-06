"""haptic_timing_gen.py — GENERATED Python consumer of the timing spec.

Do not edit by hand; regenerate with:  python tools/haptic_timing.py --write
Source of truth: docs/haptic-timing.json (spec v3).

One derivation for every Python side that needs the haptic vocabulary
(the Ziv relay, tests, tools): dot tables, cell durations, and pattern
beats — the same numbers the phone feel-tool (JS block) and the band
(firmware/haptic_out/haptic_timing.h) play. The drift guard holds all
consumers together: the checker regenerates and diffs this file too.
"""

SPEC_VERSION = 3

# The spec itself, verbatim, so the relay can serve it (GET /spec) and any
# renderer can derive its durations from the single source at runtime.
SPEC = {'version': 3, 'constants': {'cell_base_ms': 50, 'cell_per_dot_ms': 60, 'cell_gap_default_ms': 420, 'cell_gap_min_ms': 250, 'cell_gap_max_ms': 700, 'tick_ms': 70, 'tick_gap_ms': 160, 'long_buzz_ms': 600, 'tail_gap_ms': 420, 'prefix_breath_ms': 550}, 'ui': {'play_lead_ms': 500, 'loop_restart_ms': 700, 'cell_gap_step_ms': 10, 'spell_max_letters': 12}, 'letters': {'a': 1, 'b': 2, 'c': 2, 'd': 3, 'e': 2, 'f': 3, 'g': 4, 'h': 3, 'i': 2, 'j': 3, 'k': 2, 'l': 3, 'm': 3, 'n': 4, 'o': 3, 'p': 4, 'q': 5, 'r': 4, 's': 3, 't': 4, 'u': 3, 'v': 4, 'w': 4, 'x': 4, 'y': 5, 'z': 4}, 'letter_patterns': {'a': [1], 'b': [1, 2], 'c': [1, 4], 'd': [1, 4, 5], 'e': [1, 5], 'f': [1, 2, 4], 'g': [1, 2, 4, 5], 'h': [1, 2, 5], 'i': [2, 4], 'j': [2, 4, 5], 'k': [1, 3], 'l': [1, 2, 3], 'm': [1, 3, 4], 'n': [1, 3, 4, 5], 'o': [1, 3, 5], 'p': [1, 2, 3, 4], 'q': [1, 2, 3, 4, 5], 'r': [1, 2, 3, 5], 's': [2, 3, 4], 't': [2, 3, 4, 5], 'u': [1, 3, 6], 'v': [1, 2, 3, 6], 'w': [2, 4, 5, 6], 'x': [1, 3, 4, 6], 'y': [1, 3, 4, 5, 6], 'z': [1, 3, 5, 6]}, 'attention_patterns': [{'id': 'double-tap', 'word': 'double tap', 'meaning': 'acknowledge / you go', 'beats': [{'buzz_ms': 70, 'gap_after_ms': 160}, {'buzz_ms': 70, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'two short ticks, spaced; the second gap ends the pattern.'}, {'id': 'triple-pulse', 'word': 'triple pulse', 'meaning': 'reminder / look again', 'beats': [{'buzz_ms': 70, 'gap_after_ms': 160}, {'buzz_ms': 70, 'gap_after_ms': 160}, {'buzz_ms': 70, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'three short ticks; the last silence is the tail.'}, {'id': 'long-buzz', 'word': 'long buzz', 'meaning': 'error / stop', 'beats': [{'buzz_ms': 600, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'one long buzz; the following silence is the tail.'}, {'id': 'ramp-up', 'word': 'ramp up', 'meaning': 'attention building', 'beats': [{'buzz_ms': 50, 'gap_after_ms': 90}, {'buzz_ms': 90, 'gap_after_ms': 120}, {'buzz_ms': 140, 'gap_after_ms': 160}, {'buzz_ms': 200, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'each buzz grows; the final silence is the tail.'}, {'id': 'heartbeat', 'word': 'heartbeat', 'meaning': "keep alive / I'm here", 'beats': [{'buzz_ms': 70, 'gap_after_ms': 120}, {'buzz_ms': 70, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'two beats, closer first gap; the second silence is the tail.'}, {'id': 'processing', 'word': 'processing', 'meaning': 'thinking / working', 'beats': [{'buzz_ms': 70, 'gap_after_ms': 350}, {'buzz_ms': 70, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'two beats with a long first gap; the second silence is the tail.'}, {'id': 'end-of-message', 'word': 'end of message', 'meaning': 'done / return', 'beats': [{'buzz_ms': 200, 'gap_after_ms': 120}, {'buzz_ms': 140, 'gap_after_ms': 120}, {'buzz_ms': 90, 'gap_after_ms': 120}, {'buzz_ms': 50, 'gap_after_ms': 420, 'gap_ref': 'tail'}], 'note': 'a declining run that ends on the tail silence.'}], 'marks': {'ziv': ['z', 'i', 'v'], 'raz': ['r', 'a', 'z'], 'boaz': ['b', 'o', 'a', 'z'], 'razu': ['r', 'a', 'z', 'u'], 'buz': ['b', 'u', 'z']}, 'rename_examples': {'same_arc_as': 'raz', 'words': ['zar'], 'note': 'Same dot-count arc as raz.'}, 'prefix': {'mark': 'ziv', 'breath_after_mark_ms_ref': 'prefix_breath_ms', 'tails': {'message': 'double-tap', 'reminder': 'triple-pulse', 'error': 'long-buzz'}}, 'play_lead_ms': 500, 'loop_restart_ms': 700, 'cell_gap_step_ms': 10, 'spell_max_letters': 12, 'note': "Feel-tool page affordances only - the band fires patterns immediately, does not loop them, and tunes cell gap in its own config within the same envelope. spell_max_letters caps the page's spell box; the firmware accepts up to 16 (HAPTIC_OUT_MAX_WORD_LEN) so the band is never the weaker player. These two numbers are intentionally different and are NOT the same setting: spell_max_letters (12) is a page affordance that limits what the spell box headlines for the wearer, while HAPTIC_OUT_MAX_WORD_LEN (16) is the firmware's hard ceiling on word length the band will actually play. Do not unify them - the asymmetry is deliberate, and the drift guard (tools/haptic_timing.py --verify) treats the generated feel-tool JS block and the firmware header as separate consumers of the same spec, each free to use different UI vs. runtime limits."}

# Cell rule: buzz_ms = CELL_BASE_MS + CELL_PER_DOT_MS * dots.
CELL_BASE_MS = 50
CELL_PER_DOT_MS = 60

# Attention/lifecycle constants (plan §4). One beat = buzz, then silence.
TICK_MS = 70
TICK_GAP_MS = 160
LONG_BUZZ_MS = 600
TAIL_GAP_MS = 420
PREFIX_BREATH_MS = 550

# Playback-speed envelope + UI cap (spec: constants + ui blocks).
CELL_GAP_DEFAULT_MS = 420
CELL_GAP_MIN_MS = 250
CELL_GAP_MAX_MS = 700
SPELL_MAX_LETTERS = 12

# Grade-1 alphabet: dots, motor bitmask (bit n = dot n), cell ms (index 0 = 'a').
LETTERS = 'abcdefghijklmnopqrstuvwxyz'
LETTER_DOTS = {
    'a': 1,
    'b': 2,
    'c': 2,
    'd': 3,
    'e': 2,
    'f': 3,
    'g': 4,
    'h': 3,
    'i': 2,
    'j': 3,
    'k': 2,
    'l': 3,
    'm': 3,
    'n': 4,
    'o': 3,
    'p': 4,
    'q': 5,
    'r': 4,
    's': 3,
    't': 4,
    'u': 3,
    'v': 4,
    'w': 4,
    'x': 4,
    'y': 5,
    'z': 4,
}
LETTER_MASKS = {
    'a': 0x01,
    'b': 0x03,
    'c': 0x09,
    'd': 0x19,
    'e': 0x11,
    'f': 0x0B,
    'g': 0x1B,
    'h': 0x13,
    'i': 0x0A,
    'j': 0x1A,
    'k': 0x05,
    'l': 0x07,
    'm': 0x0D,
    'n': 0x1D,
    'o': 0x15,
    'p': 0x0F,
    'q': 0x1F,
    'r': 0x17,
    's': 0x0E,
    't': 0x1E,
    'u': 0x25,
    'v': 0x27,
    'w': 0x3A,
    'x': 0x2D,
    'y': 0x3D,
    'z': 0x35,
}
LETTER_MS = {
    'a': 110,
    'b': 170,
    'c': 170,
    'd': 230,
    'e': 170,
    'f': 230,
    'g': 290,
    'h': 230,
    'i': 170,
    'j': 230,
    'k': 170,
    'l': 230,
    'm': 230,
    'n': 290,
    'o': 230,
    'p': 290,
    'q': 350,
    'r': 290,
    's': 230,
    't': 290,
    'u': 230,
    'v': 290,
    'w': 290,
    'x': 290,
    'y': 350,
    'z': 290,
}

# Attention patterns, in spec order (index == the C HAPTIC_PAT_* enum).
PATTERN_IDS = (
    'double-tap',
    'triple-pulse',
    'long-buzz',
    'ramp-up',
    'heartbeat',
    'processing',
    'end-of-message',
)
PATTERN_INDEX = {pid: i for i, pid in enumerate(PATTERN_IDS)}
# id -> ((buzz_ms, gap_after_ms), ...) — the beats, in spec order.
PATTERN_BEATS = {
    'double-tap': ((70, 160), (70, 420),),
    'triple-pulse': ((70, 160), (70, 160), (70, 420),),
    'long-buzz': ((600, 420),),
    'ramp-up': ((50, 90), (90, 120), (140, 160), (200, 420),),
    'heartbeat': ((70, 120), (70, 420),),
    'processing': ((70, 350), (70, 420),),
    'end-of-message': ((200, 120), (140, 120), (90, 120), (50, 420),),
}

# Candidate marks: letters per position, in spec order (index == the C enum).
MARK_IDS = (
    'ziv',
    'raz',
    'boaz',
    'razu',
    'buz',
)
MARK_INDEX = {mid: i for i, mid in enumerate(MARK_IDS)}
MARK_CELLS = {
    'ziv': ('z', 'i', 'v'),
    'raz': ('r', 'a', 'z'),
    'boaz': ('b', 'o', 'a', 'z'),
    'razu': ('r', 'a', 'z', 'u'),
    'buz': ('b', 'u', 'z'),
}

# Name-mark prefix composition (plan §4): mark, breath, then the tail pattern.
PREFIX_MARK = 'ziv'
PREFIX_TAILS = {
    'message': 'double-tap',
    'reminder': 'triple-pulse',
    'error': 'long-buzz',
}


def cell_ms(letter: str) -> int:
    """Cell buzz duration for a letter 'a'..'z'."""
    return CELL_BASE_MS + CELL_PER_DOT_MS * LETTER_DOTS[letter]


def pattern_beats(pattern_id: str) -> tuple:
    """The (buzz_ms, gap_after_ms) beats of one attention pattern."""
    return PATTERN_BEATS[pattern_id]

