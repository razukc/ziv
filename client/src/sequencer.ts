/**
 * The pure sequencer: (utterance, spec, pace, profile) → a timeline of beats.
 *
 * This is the reference renderer's model (ziv/haptics/reference.py): a beat is
 * one buzz with its start offset, dot mask and duration; silence is the space
 * between beats. Labels follow the reference (`prefix:z`, `tail`, `cue`,
 * `working`, `cell:t`, `close`) so timelines diff line for line.
 *
 * A turn (docs/ARCHITECTURE.md §5.1):
 *
 *     [prefix: mark cells, pace gap between them, breath, the tail pattern]  when present
 *     the kind's cue pattern
 *     [working pattern]                                  once, while body_pending with no words
 *     cells: pace gap inside a word, word gap between words
 *     tail gap, then the close pattern
 *
 * The device plays the same turn segment by segment (one cell or one pattern at
 * a time) so a cue can be announced between cells, the pace can change
 * mid-utterance and the working pattern can repeat on the device's clock; the
 * flattened segments are exactly `timeline()`.
 */
import {
  CLOSE_PATTERN,
  SLOT_COUNT,
  SpecError,
  WORKING_PATTERN,
  cellMs,
  clampPace,
  encodingOf,
  patternOf,
  slotCellMs,
} from './spec.ts';
import type { Encoding, ProfileName, ResolvedSpec } from './spec.ts';
import type { Utterance } from './wire.ts';

export interface Beat {
  t_ms: number;
  /** bit n = dot n+1 raised; 0 for whole-device patterns */
  dot_mask: number;
  buzz_ms: number;
  label: string;
}

export type Phase = 'prefix' | 'tail' | 'cue' | 'working' | 'cell' | 'error' | 'close';

export interface Segment {
  phase: Phase;
  label: string;
  word_index: number | null;
  letter_index: number | null;
  letter: string | null;
  /** beats relative to the segment's start */
  beats: Beat[];
  /** from the segment's start to the end of its last buzz */
  length_ms: number;
  /** silence after `length_ms` before whatever follows */
  gap_after_ms: number;
}

export function cueFor(spec: ResolvedSpec, kind: string): string {
  const k = spec.kinds[kind];
  if (!k) throw new SpecError(`spec: no cue for kind ${JSON.stringify(kind)}`);
  return k.cue;
}

/**
 * The prefix tail: the utterance names a pattern id (ziv/wire.py), but the
 * architecture's example names a kind, so both resolve; anything else falls
 * back to the utterance kind's own tail.
 */
export function tailFor(spec: ResolvedSpec, utt: Utterance): string {
  const t = utt.prefix?.tail;
  if (t && spec.patterns[t]) return t;
  const byKind = t ? spec.kinds[t] : undefined;
  if (byKind) return byKind.tail;
  const k = spec.kinds[utt.kind];
  if (!k) throw new SpecError(`spec: no tail for kind ${JSON.stringify(utt.kind)}`);
  return k.tail;
}

/** The silence between two words: the spec's word gap, or one cell gap on a v3 spec. */
export function wordGapMs(spec: ResolvedSpec, pace_ms: number): number {
  return spec.word_gap_ms ?? pace_ms;
}

export function patternSegment(spec: ResolvedSpec, patternId: string, phase: Phase, label: string = phase): Segment {
  const beats: Beat[] = [];
  let t = 0;
  let length = 0;
  let lastGap = 0;
  for (const b of patternOf(spec, patternId)) {
    beats.push({ t_ms: t, dot_mask: 0, buzz_ms: b.buzz_ms, label });
    length = t + b.buzz_ms;
    t += b.buzz_ms + b.gap_after_ms;
    lastGap = b.gap_after_ms;
  }
  return { phase, label, word_index: null, letter_index: null, letter: null, beats, length_ms: length, gap_after_ms: lastGap };
}

export function cellSegment(
  spec: ResolvedSpec,
  ch: string,
  enc: Encoding,
  phase: 'prefix' | 'cell',
  gap_after_ms: number,
  word_index: number | null,
  letter_index: number,
): Segment {
  const letter = spec.letters[ch];
  if (!letter) throw new SpecError(`spec: no cell for ${JSON.stringify(ch)}`);
  const label = `${phase}:${ch}`;
  if (enc.encoding === 'slots') {
    // six time slots in `order`: a raised dot is a slot_ms pulse in its slot, an
    // absent dot is slot_ms of silence; slot_gap_ms after every slot but the
    // last; column_gap_ms more after the third. The cell's length is constant.
    const beats: Beat[] = [];
    let t = 0;
    enc.order.forEach((dot, k) => {
      if (letter.dots.includes(dot)) beats.push({ t_ms: t, dot_mask: 1 << (dot - 1), buzz_ms: enc.slot_ms, label });
      t += enc.slot_ms;
      if (k < SLOT_COUNT - 1) t += enc.slot_gap_ms;
      if (k === 2) t += enc.column_gap_ms;
    });
    return { phase, label, word_index, letter_index, letter: ch, beats, length_ms: slotCellMs(enc), gap_after_ms };
  }
  const ms = cellMs(spec, ch);
  return {
    phase,
    label,
    word_index,
    letter_index,
    letter: ch,
    beats: [{ t_ms: 0, dot_mask: letter.mask, buzz_ms: ms, label }],
    length_ms: ms,
    gap_after_ms,
  };
}

/** The whole turn as segments, in playing order. The count does not depend on the pace. */
export function segments(utt: Utterance, spec: ResolvedSpec, pace_ms: number, profile: ProfileName): Segment[] {
  const pace = clampPace(spec, pace_ms);
  const enc = encodingOf(spec, profile);
  const out: Segment[] = [];
  if (utt.prefix) {
    const mark = utt.prefix.mark;
    for (let i = 0; i < mark.length; i++) {
      const last = i === mark.length - 1;
      // the breath replaces the last mark cell's gap, before the tail
      out.push(cellSegment(spec, mark[i]!, enc, 'prefix', last ? spec.prefix_breath_ms : pace, null, i));
    }
    out.push(patternSegment(spec, tailFor(spec, utt), 'tail'));
  }
  out.push(patternSegment(spec, cueFor(spec, utt.kind), 'cue'));
  const words = utt.words ?? [];
  if (utt.body_pending && words.length === 0) out.push(patternSegment(spec, WORKING_PATTERN, 'working'));
  words.forEach((w, wi) => {
    for (let li = 0; li < w.length; li++) {
      const lastLetter = li === w.length - 1;
      const lastWord = wi === words.length - 1;
      // inside a word the pace; between words the word gap; after the last cell the tail gap
      const gap = !lastLetter ? pace : lastWord ? spec.tail_gap_ms : wordGapMs(spec, pace);
      out.push(cellSegment(spec, w[li]!, enc, 'cell', gap, wi, li));
    }
  });
  out.push(patternSegment(spec, CLOSE_PATTERN, 'close'));
  return out;
}

/** What plays when the body never came or came as an error: the error cue, then the close. */
export function errorSegments(spec: ResolvedSpec): Segment[] {
  return [patternSegment(spec, cueFor(spec, 'error'), 'error'), patternSegment(spec, CLOSE_PATTERN, 'close')];
}

/** The arrival cue on its own, for announcing an utterance that must wait. */
export function cueSegment(spec: ResolvedSpec, kind: string): Segment {
  return patternSegment(spec, cueFor(spec, kind), 'cue');
}

export function flatten(segs: readonly Segment[]): Beat[] {
  const out: Beat[] = [];
  let t = 0;
  for (const s of segs) {
    for (const b of s.beats) out.push({ t_ms: t + b.t_ms, dot_mask: b.dot_mask, buzz_ms: b.buzz_ms, label: b.label });
    t += s.length_ms + s.gap_after_ms;
  }
  return out;
}

/** The expected buzzes for `utt` on `profile` at `pace_ms` between cells. */
export function timeline(utt: Utterance, spec: ResolvedSpec, pace_ms: number, profile: ProfileName): Beat[] {
  return flatten(segments(utt, spec, pace_ms, profile));
}

/** First buzz to the end of the close's tail: the time budget. */
export function durationMs(utt: Utterance, spec: ResolvedSpec, pace_ms: number, profile: ProfileName): number {
  let t = 0;
  for (const s of segments(utt, spec, pace_ms, profile)) t += s.length_ms + s.gap_after_ms;
  return t;
}
