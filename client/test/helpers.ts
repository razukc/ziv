// Shared test helpers: the real spec, a v3-shaped copy of it, a fake scheduler,
// and utterance builders. Nothing here sleeps for real time.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveSpec } from '../src/spec.ts';
import type { ResolvedSpec } from '../src/spec.ts';
import type { Utterance } from '../src/wire.ts';

export const here = dirname(fileURLToPath(import.meta.url));
export const repoRoot = resolve(here, '..', '..');

export function rawSpec(): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(repoRoot, 'docs', 'haptic-timing.json'), 'utf8')) as Record<string, unknown>;
}

export function rawFixtureV4(): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(here, 'fixtures', 'spec-v4.json'), 'utf8')) as Record<string, unknown>;
}

/** The checked-in spec with every v4 addition removed: the shape a v3 relay serves. */
export function rawSpecV3(): Record<string, unknown> {
  const s = rawSpec();
  const c = { ...(s.constants as Record<string, unknown>) };
  delete c.word_gap_ms;
  delete c.working_every_ms;
  delete c.conformance_tolerance_ms;
  const out: Record<string, unknown> = { ...s, version: 3, constants: c };
  delete out.kinds;
  delete out.profiles;
  delete out.rationale;
  return out;
}

export const specV4 = (): ResolvedSpec => resolveSpec(rawSpec());
export const specV3 = (): ResolvedSpec => resolveSpec(rawSpecV3());
export const fixtureV4 = (): ResolvedSpec => resolveSpec(rawFixtureV4());

let seq = 0;
export function utt(over: Partial<Utterance> & { words?: string[] } = {}, specVersion = 4): Utterance {
  seq += 1;
  return {
    v: 1,
    id: `01TEST${String(seq).padStart(6, '0')}`,
    wearer: 'w_1',
    kind: 'message',
    from: { sender: 'tests', label: 'tests' },
    prefix: null,
    words: ['hi'],
    body_pending: false,
    source: 'sender',
    not_before: null,
    expires: null,
    spec_version: specVersion,
    ...over,
  };
}

interface Timer {
  at: number;
  fn: () => void;
  id: number;
}

/** A virtual clock with timers. `lateBy` makes every timer fire late, to test self-correction. */
export class FakeScheduler {
  now = 0;
  lateBy = 0;
  private timers: Timer[] = [];
  private seq = 0;

  readonly clock = (): number => this.now;

  readonly setTimeout = (fn: () => void, ms: number): unknown => {
    const id = ++this.seq;
    this.timers.push({ at: this.now + Math.max(0, ms), fn, id });
    return id;
  };

  readonly clearTimeout = (h: unknown): void => {
    this.timers = this.timers.filter((t) => t.id !== h);
  };

  get pending(): number {
    return this.timers.length;
  }

  /** Fire every timer due up to `t`, in order, then set the clock to `t`. */
  runUntil(t: number): void {
    for (;;) {
      this.timers.sort((a, b) => a.at - b.at || a.id - b.id);
      const next = this.timers[0];
      if (!next || next.at > t) break;
      this.timers.shift();
      this.now = Math.max(this.now, next.at + this.lateBy);
      next.fn();
    }
    this.now = Math.max(this.now, t);
  }

  /** Run a bounded horizon forward: what a session does in `horizonMs` of virtual time (re-arming timers such as pings stay pending). */
  drain(horizonMs = 120_000): void {
    this.runUntil(this.now + horizonMs);
  }

  /** Fire timers until none remain (bounded, so a timer loop fails instead of hanging). */
  runAll(limit = 100_000): void {
    let n = 0;
    while (this.timers.length) {
      if (++n > limit) throw new Error('FakeScheduler: timers never drained');
      this.timers.sort((a, b) => a.at - b.at || a.id - b.id);
      const next = this.timers.shift()!;
      this.now = Math.max(this.now, next.at + this.lateBy);
      next.fn();
    }
  }
}
