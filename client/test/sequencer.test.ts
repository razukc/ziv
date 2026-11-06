import assert from 'node:assert/strict';
import { test } from 'node:test';
import { durationMs, segments, tailFor, timeline } from '../src/sequencer.ts';
import type { Beat } from '../src/sequencer.ts';
import { clampPace, resolveSpec, SpecError } from '../src/spec.ts';
import { fixtureV4, rawFixtureV4, rawSpecV3, specV3, specV4, utt } from './helpers.ts';

const B = (t_ms: number, dot_mask: number, buzz_ms: number, label: string): Beat => ({ t_ms, dot_mask, buzz_ms, label });

test('v3 fallback: shape, kinds, word gap, working cadence, chord cells', () => {
  const s = specV3();
  assert.equal(s.version, 3);
  assert.equal(s.shape, 'v3-fallback');
  assert.deepEqual(s.kinds.message, { cue: 'double-tap', tail: 'double-tap' });
  assert.deepEqual(s.kinds.reminder, { cue: 'triple-pulse', tail: 'triple-pulse' });
  assert.deepEqual(s.kinds.error, { cue: 'long-buzz', tail: 'long-buzz' });
  assert.deepEqual(s.kinds.system, { cue: 'heartbeat', tail: 'heartbeat' });
  assert.equal(s.word_gap_ms, null);
  assert.equal(s.working_every_ms, 2000);
  assert.equal(s.profiles.single_actuator.encoding, 'chord');
  assert.equal(s.profiles.six_actuator.encoding, 'chord');
});

test('v3 fallback golden: one word, no prefix, default pace (hand-computed from docs/haptic-timing.json)', () => {
  // cue double-tap 70/160 70/420 -> cells h (3 dots: 50+180=230, mask 1|2|16=19) and i (2 dots: 170, mask 2|8=10)
  // with the 420 cell gap inside the word and the 420 tail gap before the close 200/120 140/120 90/120 50/420.
  const s = specV3();
  const got = timeline(utt({ words: ['hi'] }, 3), s, 420, 'single_actuator');
  assert.deepEqual(got, [
    B(0, 0, 70, 'cue'),
    B(230, 0, 70, 'cue'),
    B(720, 19, 230, 'cell:h'),
    B(1370, 10, 170, 'cell:i'),
    B(1960, 0, 200, 'close'),
    B(2280, 0, 140, 'close'),
    B(2540, 0, 90, 'close'),
    B(2750, 0, 50, 'close'),
  ]);
  assert.equal(durationMs(utt({ words: ['hi'] }, 3), s, 420, 'single_actuator'), 2750 + 50 + 420);
});

test('v3 fallback golden: prefix ziv + tail, then cue, words, close', () => {
  // z 290 (mask 1|4|16|32=53), i 170 (10), v 290 (1|2|4|32=39); 420 between mark cells, the 550 breath after the last,
  // tail double-tap, cue double-tap, then h/i and the close.
  const s = specV3();
  const u = utt({ words: ['hi'], prefix: { mark: 'ziv', tail: 'double-tap' } }, 3);
  assert.deepEqual(timeline(u, s, 420, 'single_actuator'), [
    B(0, 53, 290, 'prefix:z'),
    B(710, 10, 170, 'prefix:i'),
    B(1300, 39, 290, 'prefix:v'),
    B(2140, 0, 70, 'tail'),
    B(2370, 0, 70, 'tail'),
    B(2860, 0, 70, 'cue'),
    B(3090, 0, 70, 'cue'),
    B(3580, 19, 230, 'cell:h'),
    B(4230, 10, 170, 'cell:i'),
    B(4820, 0, 200, 'close'),
    B(5140, 0, 140, 'close'),
    B(5400, 0, 90, 'close'),
    B(5610, 0, 50, 'close'),
  ]);
});

test('v3 fallback: between words the gap is one cell gap; body_pending plays the working pattern once', () => {
  const s = specV3();
  const two = timeline(utt({ words: ['a', 'b'] }, 3), s, 420, 'six_actuator');
  assert.deepEqual(two.slice(2, 4), [B(720, 1, 110, 'cell:a'), B(1250, 3, 170, 'cell:b')]);
  assert.equal(two[4]!.t_ms, 1250 + 170 + 420);

  const pending = timeline(utt({ kind: 'reminder', words: [], body_pending: true }, 3), s, 420, 'single_actuator');
  assert.deepEqual(pending, [
    B(0, 0, 70, 'cue'),
    B(230, 0, 70, 'cue'),
    B(460, 0, 70, 'cue'),
    B(950, 0, 70, 'working'),
    B(1370, 0, 70, 'working'),
    B(1860, 0, 200, 'close'),
    B(2180, 0, 140, 'close'),
    B(2440, 0, 90, 'close'),
    B(2650, 0, 50, 'close'),
  ]);
});

test('v4 fixture golden: slot cells on single_actuator (slot 60, gap 40, column 100; word gap 600)', () => {
  // cell length 6*60 + 5*40 + 100 = 660; slot starts 0, 100, 200, 400, 500, 600.
  const s = fixtureV4();
  assert.equal(s.shape, 'v4');
  const got = timeline(utt({ words: ['hi'] }), s, 420, 'single_actuator');
  assert.deepEqual(got, [
    B(0, 0, 70, 'cue'),
    B(230, 0, 70, 'cue'),
    B(720, 1, 60, 'cell:h'), // dot 1 in slot 1
    B(820, 2, 60, 'cell:h'), // dot 2 in slot 2
    B(1220, 16, 60, 'cell:h'), // dot 5 in slot 5 (after the 100 column break)
    B(1900, 2, 60, 'cell:i'), // next cell at 720 + 660 + 420 = 1800; dot 2 at +100
    B(2200, 8, 60, 'cell:i'), // dot 4 at +400
    B(2880, 0, 200, 'close'), // 1800 + 660 + 420 tail gap
    B(3200, 0, 140, 'close'),
    B(3460, 0, 90, 'close'),
    B(3670, 0, 50, 'close'),
  ]);
  assert.equal(durationMs(utt({ words: ['hi'] }), s, 420, 'single_actuator'), 3670 + 50 + 420);

  // between words: the word gap replaces the cell gap
  const two = timeline(utt({ words: ['a', 'b'] }), s, 420, 'single_actuator');
  assert.deepEqual(two.slice(2, 5), [B(720, 1, 60, 'cell:a'), B(1980, 1, 60, 'cell:b'), B(2080, 2, 60, 'cell:b')]);
  assert.equal(two[5]!.t_ms, 1980 + 660 + 420);

  // the cell's length is constant whatever the letter
  const segs = segments(utt({ words: ['a', 'z'] }), s, 420, 'single_actuator');
  const cells = segs.filter((x) => x.phase === 'cell');
  assert.deepEqual(cells.map((c) => c.length_ms), [660, 660]);
  assert.deepEqual(cells.map((c) => c.beats.length), [1, 4]);
});

test('v4 fixture: six_actuator stays chord; the same utterance on both profiles differs only in the cells', () => {
  const s = fixtureV4();
  const chord = timeline(utt({ words: ['hi'] }), s, 420, 'six_actuator');
  assert.deepEqual(chord.slice(2, 4), [B(720, 19, 230, 'cell:h'), B(1370, 10, 170, 'cell:i')]);
});

test('the checked-in spec resolves as v4 and its slot cell is 530 ms', () => {
  const s = specV4();
  assert.equal(s.shape, 'v4');
  const enc = s.profiles.single_actuator;
  assert.equal(enc.encoding, 'slots');
  const segs = segments(utt({ words: ['z'] }), s, 420, 'single_actuator');
  const cell = segs.find((x) => x.phase === 'cell')!;
  assert.equal(cell.length_ms, 530);
  assert.deepEqual(cell.beats.map((b) => [b.t_ms, b.dot_mask]), [[0, 1], [160, 4], [400, 16], [480, 32]]);
});

test('prefix tail resolves a pattern id, a kind name, or falls back to the utterance kind', () => {
  const s = fixtureV4();
  assert.equal(tailFor(s, utt({ prefix: { mark: 'ziv', tail: 'triple-pulse' } })), 'triple-pulse');
  assert.equal(tailFor(s, utt({ prefix: { mark: 'ziv', tail: 'reminder' } })), 'triple-pulse');
  assert.equal(tailFor(s, utt({ kind: 'system', prefix: { mark: 'ziv', tail: 'no-such' } })), 'heartbeat');
});

test('pace is clamped to the spec envelope and the segment count does not depend on it', () => {
  const s = fixtureV4();
  assert.equal(clampPace(s, 10), 250);
  assert.equal(clampPace(s, 9999), 700);
  const u = utt({ words: ['hi', 'hi'], prefix: { mark: 'ziv', tail: 'double-tap' } });
  assert.equal(segments(u, s, 250, 'single_actuator').length, segments(u, s, 700, 'single_actuator').length);
  const fast = timeline(u, s, 250, 'single_actuator');
  const slow = timeline(u, s, 700, 'single_actuator');
  assert.ok(slow[slow.length - 1]!.t_ms > fast[fast.length - 1]!.t_ms);
});

test('a malformed spec is refused with a reason', () => {
  const bad = rawFixtureV4();
  (bad.profiles as Record<string, unknown>).single_actuator = { encoding: 'slots', slot_ms: 60, slot_gap_ms: 40 };
  assert.throws(() => resolveSpec(bad), (e: unknown) => e instanceof SpecError && /column_gap_ms/.test(e.message));
  const noClose = rawSpecV3();
  noClose.attention_patterns = (noClose.attention_patterns as { id: string }[]).filter((p) => p.id !== 'end-of-message');
  assert.throws(() => resolveSpec(noClose), /end-of-message/);
  assert.throws(() => resolveSpec({ version: 'x' }), SpecError);
});
