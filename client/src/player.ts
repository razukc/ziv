/**
 * The player schedules a timeline against an injectable clock and vibrate
 * function. Every beat has an absolute deadline (`startAt + t_ms`); each timer
 * is armed for `deadline - now()`, so a late wake-up shortens the next wait
 * instead of pushing every later beat back. Drift never accumulates.
 */
import type { Beat } from './sequencer.ts';

export interface PlayerDeps {
  now: () => number;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  /** `vibrate(0)` must stop any vibration in progress. */
  vibrate: (ms: number) => void;
}

export interface PlayOptions {
  /** planned start on the deps clock; defaults to now. May be in the near future. */
  startAt?: number;
  /** segment length including its trailing silence; `onDone` fires at `startAt + total_ms` */
  total_ms: number;
  onBeat?: (beat: Beat, index: number, at: number) => void;
  onDone?: (endAt: number) => void;
}

interface Run {
  beats: readonly Beat[];
  startAt: number;
  total: number;
  next: number;
  opts: PlayOptions;
}

/** A timer that wakes this much early still fires the beat (browsers round timers). */
export const TOLERANCE_MS = 1;

export class Player {
  private readonly d: PlayerDeps;
  private run: Run | null = null;
  private timer: unknown = null;

  constructor(deps: PlayerDeps) {
    this.d = deps;
  }

  get playing(): boolean {
    return this.run !== null;
  }

  /** Start a timeline; anything already playing is cut. */
  play(beats: readonly Beat[], opts: PlayOptions): void {
    if (this.run) this.stop();
    const startAt = opts.startAt ?? this.d.now();
    this.run = { beats, startAt, total: opts.total_ms, next: 0, opts };
    this.tick();
  }

  /** Silence now; no further beats or `onDone` from the cut run. */
  stop(): void {
    if (this.timer !== null) {
      this.d.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.run) {
      this.run = null;
      this.d.vibrate(0);
    }
  }

  private readonly tick = (): void => {
    this.timer = null;
    const run = this.run;
    if (!run) return;
    const now = this.d.now();
    while (run.next < run.beats.length) {
      const b = run.beats[run.next]!;
      if (run.startAt + b.t_ms > now + TOLERANCE_MS) break;
      run.next += 1;
      this.d.vibrate(b.buzz_ms);
      run.opts.onBeat?.(b, run.next - 1, now);
      if (this.run !== run) return; // a callback stopped or replaced this run
    }
    if (run.next >= run.beats.length) {
      const end = run.startAt + run.total;
      if (end <= now + TOLERANCE_MS) {
        this.run = null;
        run.opts.onDone?.(end);
        return;
      }
      this.timer = this.d.setTimeout(this.tick, Math.max(0, end - now));
      return;
    }
    const due = run.startAt + run.beats[run.next]!.t_ms;
    this.timer = this.d.setTimeout(this.tick, Math.max(0, due - now));
  };
}
