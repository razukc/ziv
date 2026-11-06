// The headless driver's clock: instant timers jump the clock to their deadline
// on the next turn; paced timers wait real time / divisor; both fire in
// virtual order. Driven here with fake real-time primitives, so nothing sleeps.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { VirtualClock } from '../src/virtual-clock.ts';

interface Real {
  now: number;
  immediates: (() => void)[];
  timeouts: { at: number; fn: () => void; id: number }[];
  seq: number;
}

function fakeReal(): { real: Real; deps: ConstructorParameters<typeof VirtualClock>[1]; runImmediates(): number; advance(ms: number): void } {
  const real: Real = { now: 0, immediates: [], timeouts: [], seq: 0 };
  const deps = {
    realNow: () => real.now,
    realSetTimeout: (fn: () => void, ms: number) => {
      const id = ++real.seq;
      real.timeouts.push({ at: real.now + ms, fn, id });
      return id;
    },
    realClearTimeout: (h: unknown) => {
      real.timeouts = real.timeouts.filter((t) => t.id !== h);
    },
    setImmediate: (fn: () => void) => {
      real.immediates.push(fn);
      return fn;
    },
    clearImmediate: (h: unknown) => {
      real.immediates = real.immediates.filter((f) => f !== h);
    },
  };
  return {
    real,
    deps,
    runImmediates() {
      let n = 0;
      while (real.immediates.length) {
        real.immediates.shift()!();
        n += 1;
        if (n > 1000) throw new Error('immediates never drained');
      }
      return n;
    },
    advance(ms: number) {
      const target = real.now + ms;
      for (;;) {
        real.timeouts.sort((a, b) => a.at - b.at || a.id - b.id);
        const next = real.timeouts[0];
        if (!next || next.at > target) break;
        real.timeouts.shift();
        real.now = Math.max(real.now, next.at);
        next.fn();
        this.runImmediates();
      }
      real.now = target;
    },
  };
}

test('instant timers jump the clock to each deadline in order, one per turn, without real time', () => {
  const f = fakeReal();
  const vc = new VirtualClock(100, f.deps);
  const fired: [string, number][] = [];
  vc.instant.setTimeout(() => fired.push(['b', vc.now]), 5000);
  vc.instant.setTimeout(() => fired.push(['a', vc.now]), 1000);
  const h = vc.instant.setTimeout(() => fired.push(['never', vc.now]), 3000);
  vc.instant.clearTimeout(h);
  assert.equal(f.real.timeouts.length, 0, 'no real timer is armed for instant work');
  f.runImmediates();
  assert.deepEqual(fired, [
    ['a', 1000],
    ['b', 5000],
  ]);
  assert.equal(vc.now, 5000);
  assert.equal(f.real.now, 0);
  assert.equal(vc.pending, 0);
});

test('a timer armed while firing is picked up; the clock never goes backwards', () => {
  const f = fakeReal();
  const vc = new VirtualClock(100, f.deps);
  const fired: number[] = [];
  vc.instant.setTimeout(() => {
    fired.push(vc.now);
    vc.instant.setTimeout(() => fired.push(vc.now), 10); // 2010
    vc.instant.setTimeout(() => fired.push(vc.now), 0); // 2000, fires next
  }, 2000);
  f.runImmediates();
  assert.deepEqual(fired, [2000, 2000, 2010]);
});

test('paced timers wait real time divided by the divisor and hold later instant timers until then', () => {
  const f = fakeReal();
  const vc = new VirtualClock(100, f.deps);
  const fired: [string, number, number][] = [];
  vc.paced.setTimeout(() => fired.push(['wait', vc.now, f.real.now]), 2000); // 20 ms real
  vc.instant.setTimeout(() => fired.push(['after', vc.now, f.real.now]), 3000); // virtual-later: waits for the paced one
  vc.instant.setTimeout(() => fired.push(['before', vc.now, f.real.now]), 500); // virtual-earlier: jumps now
  f.runImmediates();
  assert.deepEqual(fired, [['before', 500, 0]]);
  assert.equal(f.real.timeouts.length, 1, 'one real timer for the paced wait');
  f.advance(19);
  assert.equal(fired.length, 1);
  f.advance(1);
  assert.deepEqual(fired.slice(1), [
    ['wait', 2000, 20],
    ['after', 3000, 20],
  ]);
});

test('clearing a paced timer releases what waited behind it; a cancelled instant timer re-arms the rest', () => {
  const f = fakeReal();
  const vc = new VirtualClock(10, f.deps);
  const fired: string[] = [];
  const w = vc.paced.setTimeout(() => fired.push('wait'), 1000);
  vc.instant.setTimeout(() => fired.push('after'), 1500);
  f.runImmediates();
  assert.deepEqual(fired, []);
  vc.paced.clearTimeout(w);
  f.runImmediates();
  assert.deepEqual(fired, ['after']);
  assert.equal(f.real.timeouts.length, 0);
  vc.dispose();
  assert.equal(vc.pending, 0);
});

test('a bad divisor is refused', () => {
  assert.throws(() => new VirtualClock(0));
  assert.throws(() => new VirtualClock(-5));
});
