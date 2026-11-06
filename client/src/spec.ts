/**
 * The timing spec as the relay serves it (`GET /spec`, i.e. docs/haptic-timing.json
 * verbatim) and the resolved view every duration in this client is derived from.
 *
 * Spec v4 carries `kinds`, `profiles`, `constants.word_gap_ms` and
 * `constants.working_every_ms`. A v3 spec resolves through the documented
 * fallbacks (cue/tail from `prefix.tails` plus the relay's old kind table, word
 * gap = cell gap, working every 2000 ms, chord cells on every profile). No v4
 * number is hard-coded here: a slot width or a word gap only ever comes from the
 * spec that was fetched.
 */

export interface SpecBeat {
  buzz_ms: number;
  gap_after_ms: number;
}

export interface KindSpec {
  cue: string;
  tail: string;
}

/** A phone: one motor, a cell is six time slots in `order`. */
export interface SlotsEncoding {
  encoding: 'slots';
  slot_ms: number;
  slot_gap_ms: number;
  column_gap_ms: number;
  order: number[];
}

/** The band: the raised dots driven together for the cell's duration. */
export interface ChordEncoding {
  encoding: 'chord';
}

export type Encoding = SlotsEncoding | ChordEncoding;
export type ProfileName = 'six_actuator' | 'single_actuator';

export interface Letter {
  dots: number[];
  count: number;
  mask: number;
}

export interface ResolvedSpec {
  version: number;
  /** `v4` when kinds, profiles, word gap and working cadence all came from the spec. */
  shape: 'v4' | 'v3-fallback';
  cell_base_ms: number;
  cell_per_dot_ms: number;
  cell_gap_default_ms: number;
  cell_gap_min_ms: number;
  cell_gap_max_ms: number;
  cell_gap_step_ms: number;
  tail_gap_ms: number;
  prefix_breath_ms: number;
  /** Silence between two words. `null` means one cell gap (the v3 fallback). */
  word_gap_ms: number | null;
  working_every_ms: number;
  conformance_tolerance_ms: number | null;
  tick_ms: number | null;
  letters: Record<string, Letter>;
  patterns: Record<string, SpecBeat[]>;
  kinds: Record<string, KindSpec>;
  profiles: Record<ProfileName, Encoding>;
  close_pattern: string;
  working_pattern: string;
  prefix_mark: string | null;
}

export const CLOSE_PATTERN = 'end-of-message';
export const WORKING_PATTERN = 'processing';
export const SLOT_COUNT = 6;

// v3 fallbacks: the spec had no `kinds` section, so the relay's old constants stand in.
const V3_CUES: Record<string, string> = {
  message: 'double-tap',
  reminder: 'triple-pulse',
  error: 'long-buzz',
  system: 'heartbeat',
};
const V3_WORKING_EVERY_MS = 2000;
const V3_CELL_GAP_STEP_MS = 10;
const DEFAULT_ORDER = [1, 2, 3, 4, 5, 6];

export class SpecError extends Error {}

function obj(v: unknown, what: string): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new SpecError(`spec: ${what} must be an object`);
  return v as Record<string, unknown>;
}

function posInt(v: unknown, what: string): number {
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 0) {
    throw new SpecError(`spec: ${what} must be a non-negative integer`);
  }
  return v;
}

function optInt(v: unknown): number | null {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null;
}

export function maskOf(dots: number[]): number {
  let m = 0;
  for (const d of dots) m |= 1 << (d - 1);
  return m;
}

function parseEncoding(v: unknown, pid: string): Encoding {
  const o = obj(v, `profiles.${pid}`);
  const enc = o.encoding;
  if (enc === 'slots') {
    const orderRaw = o.order === undefined ? DEFAULT_ORDER : o.order;
    if (
      !Array.isArray(orderRaw) ||
      orderRaw.length !== SLOT_COUNT ||
      new Set(orderRaw).size !== SLOT_COUNT ||
      orderRaw.some((d) => !Number.isInteger(d) || d < 1 || d > SLOT_COUNT)
    ) {
      throw new SpecError(`spec: profiles.${pid}.order must list dots 1–6 once each`);
    }
    return {
      encoding: 'slots',
      slot_ms: posInt(o.slot_ms, `profiles.${pid}.slot_ms`),
      slot_gap_ms: posInt(o.slot_gap_ms, `profiles.${pid}.slot_gap_ms`),
      column_gap_ms: posInt(o.column_gap_ms, `profiles.${pid}.column_gap_ms`),
      order: (orderRaw as number[]).slice(),
    };
  }
  if (enc === 'chord' || enc === undefined) return { encoding: 'chord' };
  throw new SpecError(`spec: profiles.${pid}.encoding=${JSON.stringify(enc)} is not chord or slots`);
}

/** Validate a raw spec and derive the view the sequencer works from. */
export function resolveSpec(raw: unknown): ResolvedSpec {
  const s = obj(raw, 'spec');
  const version = posInt(s.version, 'version');
  const c = obj(s.constants, 'constants');
  const ui = s.ui && typeof s.ui === 'object' && !Array.isArray(s.ui) ? (s.ui as Record<string, unknown>) : {};

  const counts = obj(s.letters, 'letters');
  const pats = obj(s.letter_patterns, 'letter_patterns');
  const letters: Record<string, Letter> = {};
  for (const [ch, dotsRaw] of Object.entries(pats)) {
    if (!Array.isArray(dotsRaw) || dotsRaw.some((d) => !Number.isInteger(d) || d < 1 || d > SLOT_COUNT)) {
      throw new SpecError(`spec: letter_patterns.${ch} must list dots 1–6`);
    }
    const dots = [...(dotsRaw as number[])].sort((a, b) => a - b);
    if (counts[ch] !== dots.length) {
      throw new SpecError(`spec: letters.${ch}=${String(counts[ch])} disagrees with letter_patterns.${ch} (${dots.length} dots)`);
    }
    letters[ch] = { dots, count: dots.length, mask: maskOf(dots) };
  }
  if (Object.keys(letters).length === 0) throw new SpecError('spec: letter_patterns is empty');

  const ap = s.attention_patterns;
  if (!Array.isArray(ap)) throw new SpecError('spec: attention_patterns must be a list');
  const patterns: Record<string, SpecBeat[]> = {};
  for (const p of ap) {
    const po = obj(p, 'attention_patterns[]');
    if (typeof po.id !== 'string' || !po.id) throw new SpecError('spec: attention_patterns[].id must be a string');
    if (!Array.isArray(po.beats) || po.beats.length === 0) throw new SpecError(`spec: attention_patterns ${po.id} has no beats`);
    patterns[po.id] = po.beats.map((b, i) => {
      const bo = obj(b, `attention_patterns ${po.id} beat ${i}`);
      return {
        buzz_ms: posInt(bo.buzz_ms, `attention_patterns ${po.id} beat ${i} buzz_ms`),
        gap_after_ms: posInt(bo.gap_after_ms, `attention_patterns ${po.id} beat ${i} gap_after_ms`),
      };
    });
  }
  for (const need of [CLOSE_PATTERN, WORKING_PATTERN]) {
    if (!patterns[need]) throw new SpecError(`spec: attention_patterns lacks ${need}`);
  }

  const prefix = s.prefix && typeof s.prefix === 'object' ? (s.prefix as Record<string, unknown>) : {};
  const prefixMark = typeof prefix.mark === 'string' ? prefix.mark : null;

  // kinds: v4 section, or the v3 fallback (prefix.tails + the relay's old cue table)
  let kinds: Record<string, KindSpec> = {};
  let haveKinds = false;
  if (s.kinds && typeof s.kinds === 'object' && !Array.isArray(s.kinds)) {
    for (const [k, v] of Object.entries(s.kinds as Record<string, unknown>)) {
      const ko = obj(v, `kinds.${k}`);
      if (typeof ko.cue !== 'string' || !patterns[ko.cue]) throw new SpecError(`spec: kinds.${k}.cue names no pattern`);
      if (typeof ko.tail !== 'string' || !patterns[ko.tail]) throw new SpecError(`spec: kinds.${k}.tail names no pattern`);
      kinds[k] = { cue: ko.cue, tail: ko.tail };
    }
    haveKinds = Object.keys(kinds).length > 0;
  }
  if (!haveKinds) {
    const tails = prefix.tails && typeof prefix.tails === 'object' ? (prefix.tails as Record<string, unknown>) : {};
    kinds = {};
    for (const [k, cue] of Object.entries(V3_CUES)) {
      const t = tails[k];
      const tail = typeof t === 'string' && patterns[t] ? t : cue;
      if (!patterns[cue]) throw new SpecError(`spec: v3 fallback cue ${cue} for ${k} is not in attention_patterns`);
      kinds[k] = { cue, tail };
    }
  }

  // profiles: v4 section, or chord cells everywhere (the feel-tool's dot-count encoding)
  const profiles: Record<ProfileName, Encoding> = {
    six_actuator: { encoding: 'chord' },
    single_actuator: { encoding: 'chord' },
  };
  let haveProfiles = false;
  if (s.profiles && typeof s.profiles === 'object' && !Array.isArray(s.profiles)) {
    for (const [pid, pv] of Object.entries(s.profiles as Record<string, unknown>)) {
      if (pid === 'six_actuator' || pid === 'single_actuator') {
        profiles[pid] = parseEncoding(pv, pid);
        haveProfiles = true;
      }
    }
  }

  const wordGap = optInt(c.word_gap_ms);
  const workingEvery = optInt(c.working_every_ms);
  const minGap = posInt(c.cell_gap_min_ms, 'constants.cell_gap_min_ms');
  const maxGap = posInt(c.cell_gap_max_ms, 'constants.cell_gap_max_ms');
  if (minGap > maxGap) throw new SpecError('spec: cell_gap_min_ms exceeds cell_gap_max_ms');

  return {
    version,
    shape: haveKinds && haveProfiles && wordGap !== null && workingEvery !== null ? 'v4' : 'v3-fallback',
    cell_base_ms: posInt(c.cell_base_ms, 'constants.cell_base_ms'),
    cell_per_dot_ms: posInt(c.cell_per_dot_ms, 'constants.cell_per_dot_ms'),
    cell_gap_default_ms: Math.max(minGap, Math.min(maxGap, posInt(c.cell_gap_default_ms, 'constants.cell_gap_default_ms'))),
    cell_gap_min_ms: minGap,
    cell_gap_max_ms: maxGap,
    cell_gap_step_ms: optInt(ui.cell_gap_step_ms) ?? V3_CELL_GAP_STEP_MS,
    tail_gap_ms: posInt(c.tail_gap_ms, 'constants.tail_gap_ms'),
    prefix_breath_ms: posInt(c.prefix_breath_ms, 'constants.prefix_breath_ms'),
    word_gap_ms: wordGap,
    working_every_ms: workingEvery ?? V3_WORKING_EVERY_MS,
    conformance_tolerance_ms: optInt(c.conformance_tolerance_ms),
    tick_ms: optInt(c.tick_ms),
    letters,
    patterns,
    kinds,
    profiles,
    close_pattern: CLOSE_PATTERN,
    working_pattern: WORKING_PATTERN,
    prefix_mark: prefixMark,
  };
}

/** Chord cell duration: `cell_base_ms + cell_per_dot_ms × dots`. */
export function cellMs(spec: ResolvedSpec, ch: string): number {
  const letter = spec.letters[ch];
  if (!letter) throw new SpecError(`spec: no cell for ${JSON.stringify(ch)}`);
  return spec.cell_base_ms + spec.cell_per_dot_ms * letter.count;
}

/** Fixed duration of a slot cell: every slot, every slot gap but the last, the column break. */
export function slotCellMs(enc: SlotsEncoding): number {
  return SLOT_COUNT * enc.slot_ms + (SLOT_COUNT - 1) * enc.slot_gap_ms + enc.column_gap_ms;
}

export function clampPace(spec: ResolvedSpec, pace_ms: number): number {
  const p = Number.isFinite(pace_ms) ? Math.round(pace_ms) : spec.cell_gap_default_ms;
  return Math.max(spec.cell_gap_min_ms, Math.min(spec.cell_gap_max_ms, p));
}

export function patternOf(spec: ResolvedSpec, id: string): SpecBeat[] {
  const p = spec.patterns[id];
  if (!p) throw new SpecError(`spec: no attention pattern ${JSON.stringify(id)}`);
  return p;
}

export function encodingOf(spec: ResolvedSpec, profile: ProfileName): Encoding {
  const e = spec.profiles[profile];
  if (!e) throw new SpecError(`spec: no profile ${profile}`);
  return e;
}
