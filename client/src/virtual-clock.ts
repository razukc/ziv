/**
 * The headless driver's clock: a virtual `now()` with two kinds of timer.
 *
 * Playback (the player's beats and segment ends) runs on *instant* timers: the
 * clock jumps straight to each deadline on the next turn of the event loop, so
 * a 10 s utterance plays in milliseconds while every reported duration is the
 * exact virtual one (`played.started_ms`/`closed_ms` come from this clock).
 *
 * Waits for the outside world (the device's working-pattern wait for a body,
 * the transport's ping and backoff) run on *paced* timers: real time divided
 * by `divisor`, so a body in flight from the relay still arrives before the
 * device gives up. Timers always fire in virtual order; a paced timer that is
 * due before an instant one holds the instant one until its real moment.
 */

type Kind = 'instant' | 'paced';

interface Timer {
  id: number;
  at: number;
  kind: Kind;
  realAt: number;
  fn: () => void;
}

export interface TimerApi {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

export interface VirtualClockDeps {
  /** real milliseconds */
  realNow?: () => number;
  realSetTimeout?: (fn: () => void, ms: number) => unknown;
  realClearTimeout?: (handle: unknown) => void;
  setImmediate?: (fn: () => void) => unknown;
  clearImmediate?: (handle: unknown) => void;
}

export class VirtualClock {
  now = 0;
  readonly divisor: number;
  private timers: Timer[] = [];
  private seq = 0;
  private armed: { kind: 'immediate' | 'timeout'; handle: unknown } | null = null;
  private readonly d: Required<VirtualClockDeps>;

  constructor(divisor = 100, deps: VirtualClockDeps = {}) {
    if (!(divisor > 0)) throw new Error('VirtualClock: divisor must be positive');
    this.divisor = divisor;
    this.d = {
      realNow: deps.realNow ?? (() => performance.now()),
      realSetTimeout: deps.realSetTimeout ?? ((fn, ms) => setTimeout(fn, ms)),
      realClearTimeout: deps.realClearTimeout ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>)),
      setImmediate: deps.setImmediate ?? ((fn) => setImmediate(fn)),
      clearImmediate: deps.clearImmediate ?? ((h) => clearImmediate(h as ReturnType<typeof setImmediate>)),
    };
  }

  readonly clock = (): number => this.now;

  /** Timers that jump: the player. */
  readonly instant: TimerApi = {
    setTimeout: (fn, ms) => this.add(fn, ms, 'instant'),
    clearTimeout: (h) => this.remove(h),
  };

  /** Timers that wait real time / divisor: the device's body wait, the transport. */
  readonly paced: TimerApi = {
    setTimeout: (fn, ms) => this.add(fn, ms, 'paced'),
    clearTimeout: (h) => this.remove(h),
  };

  get pending(): number {
    return this.timers.length;
  }

  /** Stop driving; pending timers never fire. */
  dispose(): void {
    this.disarm();
    this.timers = [];
  }

  private add(fn: () => void, ms: number, kind: Kind): unknown {
    const delay = Math.max(0, Number.isFinite(ms) ? ms : 0);
    const id = ++this.seq;
    const realAt = kind === 'paced' ? this.d.realNow() + delay / this.divisor : 0;
    this.timers.push({ id, at: this.now + delay, kind, realAt, fn });
    this.arm();
    return id;
  }

  private remove(handle: unknown): void {
    const before = this.timers.length;
    this.timers = this.timers.filter((t) => t.id !== handle);
    if (this.timers.length !== before) this.arm();
  }

  private next(): Timer | null {
    if (this.timers.length === 0) return null;
    this.timers.sort((a, b) => a.at - b.at || a.id - b.id);
    return this.timers[0] ?? null;
  }

  private disarm(): void {
    const a = this.armed;
    this.armed = null;
    if (!a) return;
    if (a.kind === 'immediate') this.d.clearImmediate(a.handle);
    else this.d.realClearTimeout(a.handle);
  }

  private arm(): void {
    this.disarm();
    const t = this.next();
    if (!t) return;
    if (t.kind === 'instant') {
      this.armed = { kind: 'immediate', handle: this.d.setImmediate(this.fire) };
    } else {
      const wait = Math.max(0, t.realAt - this.d.realNow());
      this.armed = { kind: 'timeout', handle: this.d.realSetTimeout(this.fire, wait) };
    }
  }

  private readonly fire = (): void => {
    this.armed = null;
    const t = this.next();
    if (!t) return;
    if (t.kind === 'paced' && t.realAt > this.d.realNow() + 0.5) {
      this.arm(); // woke early (timer rounding): wait the rest
      return;
    }
    this.timers = this.timers.filter((x) => x.id !== t.id);
    this.now = Math.max(this.now, t.at);
    try {
      t.fn();
    } finally {
      this.arm();
    }
  };
}
