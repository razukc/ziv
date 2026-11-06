import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Player } from '../src/player.ts';
import type { Beat } from '../src/sequencer.ts';
import { FakeScheduler } from './helpers.ts';

const beats: Beat[] = [
  { t_ms: 0, dot_mask: 0, buzz_ms: 70, label: 'cue' },
  { t_ms: 230, dot_mask: 0, buzz_ms: 70, label: 'cue' },
  { t_ms: 720, dot_mask: 19, buzz_ms: 230, label: 'cell:h' },
];

function harness() {
  const sched = new FakeScheduler();
  const calls: { at: number; ms: number }[] = [];
  const player = new Player({
    now: sched.clock,
    setTimeout: sched.setTimeout,
    clearTimeout: sched.clearTimeout,
    vibrate: (ms) => calls.push({ at: sched.now, ms }),
  });
  return { sched, calls, player };
}

test('beats fire in order at their deadlines; onDone at startAt + total', () => {
  const { sched, calls, player } = harness();
  let done: number | null = null;
  player.play(beats, { total_ms: 1500, onDone: (end) => (done = end) });
  assert.deepEqual(calls, [{ at: 0, ms: 70 }]); // the first beat is synchronous
  sched.runAll();
  assert.deepEqual(calls, [
    { at: 0, ms: 70 },
    { at: 230, ms: 70 },
    { at: 720, ms: 230 },
  ]);
  assert.equal(done, 1500);
  assert.equal(player.playing, false);
});

test('late timers do not accumulate drift: each beat is late by at most one wake-up', () => {
  const { sched, calls, player } = harness();
  sched.lateBy = 7;
  const naive = new FakeScheduler();
  naive.lateBy = 7;
  player.play(beats, { total_ms: 1500 });
  sched.runAll();
  // a relative chain (setTimeout(gap) after each beat) would land at 0, 237, 734: 7 ms per hop
  assert.deepEqual(
    calls.map((c) => c.at),
    [0, 237, 727],
  );
  for (const [i, c] of calls.entries()) assert.ok(c.at - beats[i]!.t_ms <= 7, `beat ${i} drifted`);
});

test('a timer that wakes 1 ms early still fires the beat (no busy re-arm)', () => {
  const { sched, calls, player } = harness();
  sched.lateBy = -1;
  player.play(beats, { total_ms: 1500 });
  sched.runAll();
  assert.deepEqual(
    calls.map((c) => c.at),
    [0, 229, 719],
  );
});

test('startAt in the future offsets every deadline', () => {
  const { sched, calls, player } = harness();
  let done: number | null = null;
  player.play(beats, { startAt: 1000, total_ms: 1500, onDone: (end) => (done = end) });
  assert.equal(calls.length, 0);
  sched.runUntil(999);
  assert.equal(calls.length, 0);
  sched.runAll();
  assert.deepEqual(
    calls.map((c) => c.at),
    [1000, 1230, 1720],
  );
  assert.equal(done, 2500);
});

test('stop silences the motor and ends the run without onDone', () => {
  const { sched, calls, player } = harness();
  let done = false;
  player.play(beats, { total_ms: 1500, onDone: () => (done = true) });
  sched.runUntil(300);
  player.stop();
  assert.deepEqual(calls.at(-1), { at: 300, ms: 0 });
  sched.runAll();
  assert.equal(calls.length, 3); // 70, 70, then the 0
  assert.equal(done, false);
  assert.equal(player.playing, false);
});

test('play while playing cuts the first run; onBeat reports index and time', () => {
  const { sched, calls, player } = harness();
  const seen: number[] = [];
  player.play(beats, { total_ms: 1500, onBeat: (_b, i) => seen.push(i) });
  sched.runUntil(100);
  player.play(beats.slice(0, 1), { total_ms: 100, onBeat: (_b, i) => seen.push(10 + i) });
  sched.runAll();
  assert.deepEqual(seen, [0, 10]);
  assert.deepEqual(
    calls.map((c) => c.ms),
    [70, 0, 70],
  );
});
