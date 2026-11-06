// The headless device driver (src/device-cli.ts) against the fake relay: the
// instant clock plays a 10 s utterance in milliseconds with exact durations,
// --hidden-once refuses then re-hellos, --enroll exchanges a code, a 4401 is
// a clean exit, body_pending waits for the body, idle-exit leaves on its own.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';
import { resolve } from 'node:path';
import { after, test } from 'node:test';
import { durationMs } from '../src/sequencer.ts';
import { parseArgs, relayUrls, UsageError } from '../src/device-cli.ts';
import type { UpFrame } from '../src/wire.ts';
import { FakeRelayHttp, withTimeout } from './fake-relay-http.ts';
import { here, specV4, utt } from './helpers.ts';

const CLI = resolve(here, '..', 'src', 'device-cli.ts');
const spec = specV4();

interface Run {
  child: ChildProcess;
  events: Record<string, unknown>[];
  stderr: string[];
  exit: Promise<number | null>;
  eventsOf(name: string): Record<string, unknown>[];
  until(pred: () => boolean, what: string): Promise<void>;
}

const runs: Run[] = [];
const relays: FakeRelayHttp[] = [];
after(async () => {
  for (const r of runs) if (r.child.exitCode === null) r.child.kill('SIGKILL');
  for (const r of relays) await r.close();
});

async function relay(): Promise<FakeRelayHttp> {
  const r = await FakeRelayHttp.start();
  relays.push(r);
  return r;
}

function cli(args: string[]): Run {
  const child = spawn(process.execPath, [CLI, ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
  const events: Record<string, unknown>[] = [];
  const stderr: string[] = [];
  let buf = '';
  child.stdout!.setEncoding('utf8');
  child.stdout!.on('data', (chunk: string) => {
    buf += chunk;
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (line.trim()) events.push(JSON.parse(line) as Record<string, unknown>);
    }
  });
  child.stderr!.setEncoding('utf8');
  child.stderr!.on('data', (chunk: string) => stderr.push(chunk));
  const exit = new Promise<number | null>((r) => child.on('exit', (code) => r(code)));
  const run: Run = {
    child,
    events,
    stderr,
    exit,
    eventsOf: (name) => events.filter((e) => e.event === name),
    until: (pred, what) =>
      withTimeout(
        new Promise<void>((res) => {
          const check = (): void => {
            if (pred()) res();
            else setTimeout(check, 5);
          };
          check();
        }),
        `${what} (events: ${events.map((e) => String(e.event)).join(',')}; stderr: ${stderr.join('').slice(-400)})`,
      ),
  };
  runs.push(run);
  return run;
}

const types = (frames: UpFrame[]): string[] =>
  frames.map((f) => (f.type === 'progress' ? `progress:${f.phase}${f.word_index ?? ''}` : f.type === 'nack' ? `nack:${f.reason}` : f.type));

test('arguments: required flags, bounds, and relay URL derivation', () => {
  const a = parseArgs(['--relay', 'ws://127.0.0.1:1/ws', '--key', 'k'.repeat(16), '--utterances', '2', '--idle-exit', '500', '--hidden-once', '--profile=six_actuator']);
  assert.equal(a.utterances, 2);
  assert.equal(a.idleExitMs, 500);
  assert.equal(a.hiddenOnce, true);
  assert.equal(a.profile, 'six_actuator');
  assert.equal(a.clock, 'instant');
  assert.throws(() => parseArgs(['--key', 'k'.repeat(16)]), UsageError);
  assert.throws(() => parseArgs(['--relay', 'ws://x']), UsageError);
  assert.throws(() => parseArgs(['--relay', 'ws://x', '--key', 'short']), UsageError);
  assert.throws(() => parseArgs(['--relay', 'ws://x', '--key', 'k'.repeat(16), '--clock', 'fast']), UsageError);
  assert.throws(() => parseArgs(['--relay', 'ws://x', '--key', 'k'.repeat(16), '--utterances', '0']), UsageError);
  assert.throws(() => parseArgs(['--relay', 'ws://x', '--key', 'k'.repeat(16), '--bogus']), UsageError);
  assert.deepEqual(relayUrls('ws://127.0.0.1:8787'), { http: 'http://127.0.0.1:8787', ws: 'ws://127.0.0.1:8787/ws' });
  assert.deepEqual(relayUrls('ws://127.0.0.1:8787/ws'), { http: 'http://127.0.0.1:8787', ws: 'ws://127.0.0.1:8787/ws' });
  assert.deepEqual(relayUrls('https://relay.example/ziv/'), { http: 'https://relay.example/ziv', ws: 'wss://relay.example/ziv/ws' });
  assert.deepEqual(relayUrls('http://localhost:9'), { http: 'http://localhost:9', ws: 'ws://localhost:9/ws' });
});

test('instant clock: a long utterance plays in milliseconds and reports its exact duration, then exits 0 after the relay saw it', async () => {
  const r = await relay();
  const started = performance.now();
  const run = cli(['--relay', r.url, '--key', r.key, '--utterances', '1', '--idle-exit', '6000']);
  const conn = await r.connection(0);
  const hello = conn.frames[0]!;
  assert.equal(hello.type, 'hello');
  if (hello.type !== 'hello') return;
  assert.equal(hello.device_key, r.key);
  assert.equal(hello.profile, 'single_actuator');
  assert.equal(hello.spec_version, spec.version);
  const u = utt({ words: ['hello', 'there', 'friend'], prefix: { mark: 'ziv', tail: 'double-tap' } });
  const expected = durationMs(u, spec, 420, 'single_actuator');
  assert.ok(expected > 8000, `the utterance takes ${expected} ms at pace 420: long enough to prove the jump`);
  r.ack(conn, [u]);
  await r.frame(conn, (f) => f.type === 'played', 'played');
  await r.frame(conn, (f) => f.type === 'ping', 'the ping after played');
  assert.deepEqual(types(conn.frames.slice(1, -1)), ['progress:cue', 'progress:word0', 'progress:word1', 'progress:word2', 'progress:close', 'played']);
  const played = conn.frames.find((f) => f.type === 'played')!;
  if (played.type === 'played') assert.equal(played.closed_ms - played.started_ms, expected);
  r.send(conn, { type: 'pong' });
  const code = await withTimeout(run.exit, 'exit');
  assert.equal(code, 0, run.stderr.join(''));
  const elapsed = performance.now() - started;
  assert.ok(elapsed < expected / 2, `played ${expected} ms of utterance in ${Math.round(elapsed)} ms real`);
  assert.deepEqual(
    run.events.map((e) => e.event).filter((e) => e !== 'socket'),
    ['spec', 'hello.ack', 'open', 'progress', 'progress', 'progress', 'progress', 'progress', 'played', 'exit'],
  );
  const open = run.eventsOf('open')[0]!;
  assert.equal(open.via, 'resend');
  assert.deepEqual(open.words, ['hello', 'there', 'friend']);
  assert.equal(open.body_pending, false);
  const exit = run.eventsOf('exit')[0]!;
  assert.equal(exit.reason, 'played');
  assert.equal(exit.played, 1);
  assert.equal(run.eventsOf('hello.ack')[0]!.device, 'd_cli');
  assert.doesNotMatch(run.stderr.join(''), /hello there friend/, 'the wire log never carries message text');
});

test('--hidden-once: the first open is refused with hidden, then a fresh hello asks for it back and it plays', async () => {
  const r = await relay();
  const run = cli(['--relay', r.url, '--key', r.key, '--utterances', '1', '--idle-exit', '6000', '--hidden-once', '--hidden-reconnect-ms', '50']);
  const c1 = await r.connection(0);
  const u = utt({ words: ['meds', 'nine'] });
  r.ack(c1, [u]);
  await r.frame(c1, (f) => f.type === 'nack', 'the hidden nack');
  assert.deepEqual(types(c1.frames), ['hello', 'nack:hidden']);
  const c2 = await r.connection(1);
  const hello2 = c2.frames[0]!;
  assert.equal(hello2.type, 'hello');
  if (hello2.type === 'hello') {
    assert.deepEqual(hello2.held, []);
    assert.equal(hello2.last_acked, null);
  }
  await r.until(() => c1.closed, 'the first socket closed');
  r.ack(c2, [u]); // the relay re-offers what the device refused
  await r.frame(c2, (f) => f.type === 'played', 'played');
  await r.frame(c2, (f) => f.type === 'ping', 'the ping after played');
  assert.deepEqual(types(c2.frames.slice(1, -1)), ['progress:cue', 'progress:word0', 'progress:word1', 'progress:close', 'played']);
  r.send(c2, { type: 'pong' });
  assert.equal(await withTimeout(run.exit, 'exit'), 0, run.stderr.join(''));
  assert.deepEqual(run.eventsOf('nack'), [{ ...run.eventsOf('nack')[0], id: u.id, reason: 'hidden' }]);
  assert.equal(run.eventsOf('hello.ack').length, 2);
  assert.equal(run.eventsOf('played').length, 1);
});

test('--enroll exchanges the code for a key and says hello with it', async () => {
  const r = await relay();
  const run = cli(['--relay', r.url + '/ws', '--enroll', 'abc123', '--name', 'bench', '--profile', 'six_actuator', '--idle-exit', '200']);
  const conn = await r.connection(0);
  const hello = conn.frames[0]!;
  assert.equal(hello.type, 'hello');
  if (hello.type === 'hello') {
    assert.equal(hello.device_key, r.key);
    assert.equal(hello.profile, 'six_actuator');
  }
  assert.deepEqual(r.enrolls, [{ code: 'ABC123', profile: 'six_actuator', name: 'bench' }]);
  r.ack(conn);
  assert.equal(await withTimeout(run.exit, 'exit'), 0, run.stderr.join(''));
  const enrolled = run.eventsOf('enrolled')[0]!;
  assert.equal(enrolled.device, 'd_cli');
  assert.equal(enrolled.device_key, r.key);
  assert.equal(run.eventsOf('exit')[0]!.reason, 'idle');
  assert.equal(run.eventsOf('exit')[0]!.played, 0);
});

test('a bad enroll code and a refused key are clean non-zero exits', async () => {
  const r = await relay();
  const bad = cli(['--relay', r.url, '--enroll', 'NOPE42', '--idle-exit', '200']);
  assert.equal(await withTimeout(bad.exit, 'exit'), 1);
  assert.equal(bad.eventsOf('exit')[0]!.reason, 'enroll_failed');
  assert.equal(bad.eventsOf('exit')[0]!.status, 401);

  const refused = cli(['--relay', r.url, '--key', 'wrong-key-wrong-key-wrong', '--idle-exit', '5000']);
  const conn = await r.connection(0);
  r.send(conn, { type: 'error', reason: 'unauthorized', detail: 'unknown device key' });
  conn.ws.close(4401, 'unauthorized');
  assert.equal(await withTimeout(refused.exit, 'exit'), 3, refused.stderr.join(''));
  assert.equal(refused.eventsOf('refused')[0]!.code, 4401);
  assert.equal(refused.eventsOf('error')[0]!.reason, 'unauthorized');
  assert.equal(refused.eventsOf('exit')[0]!.reason, 'refused');
  assert.equal(r.conns.length, 1, 'no reconnect after a refusal');
});

test('body_pending: the working pattern waits for the body in paced time, then the words play', async () => {
  const r = await relay();
  const run = cli(['--relay', r.url, '--key', r.key, '--utterances', '1', '--idle-exit', '6000']);
  const conn = await r.connection(0);
  const u = utt({ words: [], body_pending: true, kind: 'reminder', prefix: { mark: 'ziv', tail: 'triple-pulse' } });
  r.ack(conn);
  r.send(conn, { type: 'utterance.open', utterance: u });
  await r.frame(conn, (f) => f.type === 'progress' && f.phase === 'working', 'progress working');
  // a few working repeats happen while the body is on its way (20 ms real each at the default divisor)
  await new Promise((res) => setTimeout(res, 60));
  assert.ok(!conn.frames.some((f) => f.type === 'nack'), 'no body_timeout yet: the wait is paced, not jumped');
  r.send(conn, { type: 'utterance.body', id: u.id, words: ['pills', 'now'], source: 'live' });
  await r.frame(conn, (f) => f.type === 'played', 'played');
  await r.frame(conn, (f) => f.type === 'ping', 'the ping after played');
  const t = types(conn.frames);
  assert.deepEqual(t.slice(0, 3), ['hello', 'progress:cue', 'progress:working']);
  assert.deepEqual(t.slice(-5), ['progress:word0', 'progress:word1', 'progress:close', 'played', 'ping']);
  r.send(conn, { type: 'pong' });
  assert.equal(await withTimeout(run.exit, 'exit'), 0, run.stderr.join(''));
  const open = run.eventsOf('open')[0]!;
  assert.equal(open.via, 'open');
  assert.equal(open.body_pending, true);
  const body = run.eventsOf('body')[0]!;
  assert.deepEqual(body.words, ['pills', 'now']);
  assert.equal(body.source, 'live');
  assert.equal(body.error, null);
});

test('a body that never comes times out on the device clock without a real 20 s wait', async () => {
  const r = await relay();
  const started = performance.now();
  const run = cli(['--relay', r.url, '--key', r.key, '--idle-exit', '400']);
  const conn = await r.connection(0);
  const u = utt({ words: [], body_pending: true });
  r.ack(conn, [u]);
  const nack = await r.frame(conn, (f) => f.type === 'nack', 'the body_timeout nack');
  assert.ok(performance.now() - started < 5000, 'the 20 s device timeout ran at 1/100 real time');
  if (nack.type === 'nack') assert.equal(nack.reason, 'body_timeout');
  assert.equal(await withTimeout(run.exit, 'exit'), 0, run.stderr.join(''));
  assert.equal(run.eventsOf('exit')[0]!.reason, 'idle');
});

test('real clock: timers are wall-clock, so a short utterance takes its real duration', async () => {
  const r = await relay();
  const run = cli(['--relay', r.url, '--key', r.key, '--clock', 'real', '--utterances', '1', '--idle-exit', '6000']);
  const conn = await r.connection(0);
  const u = utt({ words: ['a'] });
  const expected = durationMs(u, spec, 250, 'single_actuator');
  const t0 = performance.now();
  r.ack(conn, [u], 250);
  const played = await r.frame(conn, (f) => f.type === 'played', 'played');
  const took = performance.now() - t0;
  assert.ok(took >= expected * 0.9, `real clock: ${Math.round(took)} ms for a ${expected} ms utterance`);
  if (played.type === 'played') {
    // on a wall clock a late wake-up may delay the next segment a little; it never shortens anything
    const reported = played.closed_ms - played.started_ms;
    assert.ok(reported >= expected && reported <= expected + 250, `reported ${reported} ms for ${expected} ms`);
  }
  r.send(conn, { type: 'pong' });
  assert.equal(await withTimeout(run.exit, 'exit'), 0, run.stderr.join(''));
});
