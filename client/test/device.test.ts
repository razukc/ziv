// The device against a fake relay over `ws`: the hello-first handshake,
// progress/played ordering, nack on hidden, cancel handling, resume with held
// ids, body_pending, interjected cues, advance modes. Device timers run on a
// fake scheduler; only the socket is real.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { WebSocketServer } from 'ws';
import type { WebSocket as ServerSocket } from 'ws';
import { Device } from '../src/device.ts';
import { Player } from '../src/player.ts';
import { MemoryQueueStore } from '../src/queue.ts';
import type { QueueSnapshot } from '../src/queue.ts';
import { durationMs, timeline } from '../src/sequencer.ts';
import { Transport } from '../src/transport.ts';
import type { DownFrame, Prefs, UpFrame, Utterance } from '../src/wire.ts';
import { FakeScheduler, specV4, utt } from './helpers.ts';

const spec = specV4();
const WAIT_MS = 5000;

/** Poll a condition on the device (frames cross a real socket, so the device acts a tick later). */
function waitFor(pred: () => boolean, what: string): Promise<void> {
  return withTimeout(
    new Promise<void>((resolve) => {
      const check = (): void => {
        if (pred()) resolve();
        else setTimeout(check, 5);
      };
      check();
    }),
    what,
  );
}

function withTimeout<T>(p: Promise<T>, what: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`timed out waiting for ${what}`)), WAIT_MS);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      },
    );
  });
}

class FakeRelay {
  readonly wss: WebSocketServer;
  readonly url: string;
  readonly frames: UpFrame[] = [];
  private sockets: ServerSocket[] = [];
  private waiters: (() => void)[] = [];

  private constructor(wss: WebSocketServer, port: number) {
    this.wss = wss;
    this.url = `ws://127.0.0.1:${port}/ws`;
    wss.on('connection', (ws) => {
      this.sockets.push(ws);
      ws.on('message', (data) => {
        this.frames.push(JSON.parse(data.toString()) as UpFrame);
        this.wake();
      });
      this.wake();
    });
  }

  static async start(): Promise<FakeRelay> {
    const wss = new WebSocketServer({ port: 0, host: '127.0.0.1' });
    await withTimeout(new Promise<void>((r) => wss.once('listening', () => r())), 'relay listening');
    const addr = wss.address();
    if (!addr || typeof addr === 'string') throw new Error('no port');
    return new FakeRelay(wss, addr.port);
  }

  private wake(): void {
    const ws = this.waiters;
    this.waiters = [];
    for (const w of ws) w();
  }

  private until(pred: () => boolean, what: string): Promise<void> {
    if (pred()) return Promise.resolve();
    return withTimeout(
      new Promise<void>((resolve) => {
        const check = (): void => {
          if (pred()) resolve();
          else this.waiters.push(check);
        };
        this.waiters.push(check);
      }),
      what,
    );
  }

  get connections(): number {
    return this.sockets.length;
  }

  connected(n = 1): Promise<void> {
    return this.until(() => this.sockets.length >= n, `connection ${n}`);
  }

  /** Wait until at least `n` frames have arrived in total. */
  count(n: number): Promise<void> {
    return this.until(() => this.frames.length >= n, `${n} frames (have ${this.frames.length}: ${this.frames.map((f) => f.type).join(',')})`);
  }

  /** Wait for a frame matching `pred` (from index `from`), return its index. */
  async frame(pred: (f: UpFrame) => boolean, from = 0, what = 'frame'): Promise<number> {
    await this.until(() => this.frames.slice(from).some(pred), what);
    return from + this.frames.slice(from).findIndex(pred);
  }

  send(frame: DownFrame, conn = this.sockets.length - 1): void {
    const ws = this.sockets[conn];
    if (!ws) throw new Error('no socket');
    ws.send(JSON.stringify(frame));
  }

  ack(prefs: Prefs = {}, resend: Utterance[] = []): void {
    this.send({ type: 'hello.ack', wearer: 'w_1', device: 'd_web', spec_version: spec.version, prefs, resend });
  }

  dropConnection(conn = this.sockets.length - 1): void {
    this.sockets[conn]?.close();
  }

  close(): Promise<void> {
    for (const s of this.sockets) s.terminate();
    return new Promise((r) => this.wss.close(() => r()));
  }
}

interface Rig {
  relay: FakeRelay;
  sched: FakeScheduler;
  device: Device;
  transport: Transport;
  vibrations: number[];
  hidden: { value: boolean };
  store: MemoryQueueStore;
  log: string[];
  close(): Promise<void>;
}

const rigs: Rig[] = [];
after(async () => {
  for (const r of rigs) await r.close();
});

async function rig(opts: { seed?: QueueSnapshot; queueCap?: number; bodyTimeoutMs?: number; pingEveryMs?: number } = {}): Promise<Rig> {
  const relay = await FakeRelay.start();
  const sched = new FakeScheduler();
  const vibrations: number[] = [];
  const hidden = { value: false };
  const store = new MemoryQueueStore();
  if (opts.seed) await store.save(opts.seed);
  const log: string[] = [];
  const player = new Player({ now: sched.clock, setTimeout: sched.setTimeout, clearTimeout: sched.clearTimeout, vibrate: (ms) => vibrations.push(ms) });
  let transport: Transport | null = null;
  const device = new Device({
    spec,
    profile: 'single_actuator',
    player,
    store,
    now: sched.clock,
    setTimeout: sched.setTimeout,
    clearTimeout: sched.clearTimeout,
    send: (f) => void transport?.send(f),
    isHidden: () => hidden.value,
    log: (l) => log.push(l),
    queueCap: opts.queueCap,
    bodyTimeoutMs: opts.bodyTimeoutMs,
  });
  await device.restore();
  transport = new Transport({
    url: relay.url,
    WebSocket: globalThis.WebSocket,
    makeHello: () => device.hello('k'.repeat(32)),
    onFrame: (f) => device.handleFrame(f),
    log: (l) => log.push(l),
    setTimeout: sched.setTimeout,
    clearTimeout: sched.clearTimeout,
    pingEveryMs: opts.pingEveryMs ?? 3_600_000, // out of every test's horizon unless a test asks for pings
  });
  const r: Rig = {
    relay,
    sched,
    device,
    transport,
    vibrations,
    hidden,
    store,
    log,
    close: async () => {
      transport?.close();
      await relay.close();
    },
  };
  rigs.push(r);
  return r;
}

const types = (frames: UpFrame[]): string[] => frames.map((f) => (f.type === 'progress' ? `progress:${f.phase}${f.word_index ?? ''}` : f.type === 'nack' ? `nack:${f.reason}` : f.type));

test('hello is the first frame, then progress at cue, each word and close, then played', async () => {
  const { relay, sched, device, transport, vibrations } = await rig();
  transport.connect();
  await relay.count(1);
  const hello = relay.frames[0]!;
  assert.equal(hello.type, 'hello');
  if (hello.type !== 'hello') return;
  assert.equal(hello.profile, 'single_actuator');
  assert.equal(hello.spec_version, spec.version);
  assert.equal(hello.pace_ms, spec.cell_gap_default_ms);
  assert.equal(hello.last_acked, null);
  assert.deepEqual(hello.held, []);
  assert.equal(hello.device_key, 'k'.repeat(32));

  relay.ack({ pace_ms: 420, advance: 'auto' });
  const u = utt({ words: ['meds', 'nine'], prefix: { mark: 'ziv', tail: 'double-tap' } });
  relay.send({ type: 'utterance.open', utterance: u });
  await waitFor(() => device.view().current?.id === u.id, 'the open to reach the device');
  assert.equal(relay.frames.length, 1, 'with a prefix, nothing is reported before the cue');
  sched.drain();
  await relay.frame((f) => f.type === 'played', 1, 'played');
  assert.deepEqual(types(relay.frames.slice(1)), ['progress:cue', 'progress:word0', 'progress:word1', 'progress:close', 'played']);
  const played = relay.frames.at(-1)!;
  if (played.type === 'played') {
    assert.equal(played.id, u.id);
    assert.equal(played.closed_ms - played.started_ms, durationMs(u, spec, 420, 'single_actuator'));
  }
  const expected = timeline(u, spec, 420, 'single_actuator');
  assert.deepEqual(vibrations, expected.map((b) => b.buzz_ms));
  assert.equal(device.lastAckedId, u.id);
  assert.deepEqual(device.held, []);
});

test('reconnect sends a fresh hello first, carrying last_acked and held', async () => {
  const { relay, sched, transport } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack();
  const a = utt({ words: ['hi'] });
  relay.send({ type: 'utterance.open', utterance: a });
  await relay.frame((f) => f.type === 'progress', 1, 'progress');
  sched.drain();
  await relay.frame((f) => f.type === 'played', 1, 'played');
  const before = relay.frames.length;
  relay.dropConnection();
  await new Promise((r) => setTimeout(r, 50));
  sched.runUntil(sched.now + 1000); // the first backoff
  await relay.connected(2);
  await relay.count(before + 1);
  const hello = relay.frames[before]!;
  assert.equal(hello.type, 'hello');
  if (hello.type === 'hello') {
    assert.equal(hello.last_acked, a.id);
    assert.deepEqual(hello.held, []);
  }
});

test('hidden: an open is refused with nack hidden; going hidden mid-utterance stops and nacks; a resend plays', async () => {
  const { relay, sched, device, transport, vibrations, hidden } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack();
  hidden.value = true;
  const a = utt({ words: ['hi'] });
  relay.send({ type: 'utterance.open', utterance: a });
  await relay.frame((f) => f.type === 'nack', 1, 'nack');
  assert.deepEqual(types(relay.frames.slice(1)), ['nack:hidden']);
  assert.equal(vibrations.length, 0);
  assert.deepEqual(device.held, []);

  hidden.value = false;
  const b = utt({ words: ['hello', 'world'] });
  relay.send({ type: 'utterance.open', utterance: b });
  await relay.frame((f) => f.type === 'progress' && f.id === b.id, 1, 'progress b');
  sched.runUntil(sched.now + 1500); // into the first word
  assert.ok(vibrations.length > 2);
  hidden.value = true;
  device.onVisibility(true);
  await relay.frame((f) => f.type === 'nack' && f.id === b.id, 1, 'nack b');
  assert.equal(vibrations.at(-1), 0, 'vibrate(0) silences the motor');
  assert.deepEqual(device.held, []);
  const n = vibrations.length;
  sched.drain();
  assert.equal(vibrations.length, n, 'nothing plays while hidden');

  hidden.value = false;
  device.onVisibility(false);
  relay.send({ type: 'utterance.open', utterance: b }); // the relay resends; the device plays it
  await relay.frame((f) => f.type === 'progress' && f.phase === 'cue' && f.id === b.id, relay.frames.length, 'cue again');
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === b.id, 1, 'played b');
});

test('cancel removes a queued utterance and stops the current one', async () => {
  const { relay, sched, device, transport, vibrations } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack();
  const a = utt({ words: ['hello'] });
  const b = utt({ words: ['world'] });
  relay.send({ type: 'utterance.open', utterance: a });
  relay.send({ type: 'utterance.open', utterance: b });
  relay.send({ type: 'utterance.cancel', id: b.id, reason: 'cancelled_by_sender' });
  await relay.frame((f) => f.type === 'progress' && f.id === a.id, 1, 'progress a');
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(device.held, [a.id]);
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === a.id, 1, 'played a');
  assert.ok(!relay.frames.some((f) => f.type === 'progress' && f.id === b.id), 'b was never announced');

  const c = utt({ words: ['again'] });
  relay.send({ type: 'utterance.open', utterance: c });
  await relay.frame((f) => f.type === 'progress' && f.id === c.id, 1, 'progress c');
  sched.runUntil(sched.now + 1000);
  const n = vibrations.length;
  relay.send({ type: 'utterance.cancel', id: c.id, reason: 'cancelled_by_sender' });
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(vibrations.at(-1), 0);
  assert.deepEqual(device.held, []);
  sched.drain();
  assert.equal(vibrations.length, n + 1);
  assert.ok(!relay.frames.some((f) => f.type === 'played' && f.id === c.id));
  assert.equal(device.view().phase, 'idle');
});

test('a reload resumes: hello carries held ids and last_acked, then the held utterances play', async () => {
  const held = [utt({ words: ['one'] }), utt({ words: ['two'] })];
  const { relay, sched, transport } = await rig({
    seed: { entries: held.map((u) => ({ utt: u, body: null, cued: true, received_at: 0 })), last_acked: '01TESTACKED' },
  });
  transport.connect();
  await relay.count(1);
  const hello = relay.frames[0]!;
  assert.equal(hello.type, 'hello');
  if (hello.type === 'hello') {
    assert.deepEqual(hello.held, held.map((u) => u.id));
    assert.equal(hello.last_acked, '01TESTACKED');
  }
  relay.ack();
  await relay.frame((f) => f.type === 'progress' && f.phase === 'cue' && f.id === held[0]!.id, 1, 'cue one (replayed after a reload)');
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === held[1]!.id, 1, 'played two');
  assert.deepEqual(types(relay.frames.slice(1)), [
    'progress:cue',
    'progress:word0',
    'progress:close',
    'played',
    'progress:cue',
    'progress:word0',
    'progress:close',
    'played',
  ]);
});

test('spec mismatch, duplicates and a full queue are refused loudly', async () => {
  const { relay, sched, device, transport } = await rig({ queueCap: 1 });
  transport.connect();
  await relay.count(1);
  relay.ack();
  relay.send({ type: 'utterance.open', utterance: utt({ words: ['hi'] }, 99) });
  await relay.frame((f) => f.type === 'nack' && f.reason === 'spec_mismatch', 1, 'nack spec_mismatch');
  const a = utt({ words: ['hi'] });
  relay.send({ type: 'utterance.open', utterance: a });
  relay.send({ type: 'utterance.open', utterance: a });
  relay.send({ type: 'utterance.open', utterance: utt({ words: ['no'] }) });
  await relay.frame((f) => f.type === 'nack' && f.reason === 'queue_full', 1, 'nack queue_full');
  assert.deepEqual(device.held, [a.id]);
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === a.id, 1, 'played');
  assert.equal(relay.frames.filter((f) => f.type === 'played').length, 1);
});

test('body_pending: working repeats on the device clock until the body comes; then the words', async () => {
  const { relay, sched, device, transport, vibrations } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack();
  const a = utt({ kind: 'reminder', words: [], body_pending: true, prefix: { mark: 'ziv', tail: 'triple-pulse' } });
  relay.send({ type: 'utterance.open', utterance: a });
  await waitFor(() => device.view().current?.id === a.id, 'the open to reach the device');
  sched.runUntil(sched.now + 9000); // prefix, cue, then a few working repeats
  await relay.frame((f) => f.type === 'progress' && f.phase === 'working', 1, 'working');
  const workingBeats = vibrations.length;
  assert.ok(workingBeats >= 7, `expected repeats of the working pattern, saw ${workingBeats} beats`);
  relay.send({ type: 'utterance.body', id: a.id, words: ['meds', 'now'] });
  await new Promise((r) => setTimeout(r, 30));
  sched.drain();
  await relay.frame((f) => f.type === 'played', 1, 'played');
  const t = types(relay.frames.slice(1));
  assert.deepEqual(t.filter((x) => x !== 'progress:working'), ['progress:cue', 'progress:word0', 'progress:word1', 'progress:close', 'played']);
  assert.equal(t.filter((x) => x === 'progress:working').length, 1);
});

test('body timeout: nack body_timeout, the error pattern and the close play, no played', async () => {
  const { relay, sched, transport, vibrations } = await rig({ bodyTimeoutMs: 5000 });
  transport.connect();
  await relay.count(1);
  relay.ack();
  const a = utt({ kind: 'message', words: [], body_pending: true });
  relay.send({ type: 'utterance.open', utterance: a });
  await relay.frame((f) => f.type === 'progress', 1, 'cue');
  sched.drain();
  await relay.frame((f) => f.type === 'nack' && f.reason === 'body_timeout', 1, 'nack body_timeout');
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(!relay.frames.some((f) => f.type === 'played'));
  // the error cue (long-buzz) then the close's declining run are the last buzzes
  assert.deepEqual(vibrations.slice(-5), [600, 200, 140, 90, 50]);
});

test('an utterance arriving mid-utterance is cued between cells, then plays without repeating its cue', async () => {
  const { relay, sched, transport } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack();
  const a = utt({ words: ['hello', 'world'] });
  const b = utt({ kind: 'reminder', words: ['pills'] });
  relay.send({ type: 'utterance.open', utterance: a });
  await relay.frame((f) => f.type === 'progress' && f.id === a.id, 1, 'cue a');
  sched.runUntil(sched.now + 100);
  relay.send({ type: 'utterance.open', utterance: b });
  await new Promise((r) => setTimeout(r, 30));
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === b.id, 1, 'played b');
  const seq = relay.frames.slice(1).map((f) => `${f.type === 'progress' ? `progress:${f.phase}${f.word_index ?? ''}` : f.type}@${'id' in f ? (f.id === a.id ? 'a' : 'b') : ''}`);
  assert.deepEqual(seq, [
    'progress:cue@a',
    'progress:cue@b', // announced at the first boundary, before a's first word
    'progress:word0@a',
    'progress:word1@a',
    'progress:close@a',
    'played@a',
    'progress:word0@b', // b's cue is not repeated at its turn
    'progress:close@b',
    'played@b',
  ]);
});

test('advance=tap: the next utterance waits for the wearer; controls go on the wire', async () => {
  const { relay, sched, device, transport } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack({ advance: 'tap' });
  const a = utt({ words: ['one'] });
  const b = utt({ words: ['two'] });
  relay.send({ type: 'utterance.open', utterance: a });
  relay.send({ type: 'utterance.open', utterance: b });
  await relay.frame((f) => f.type === 'progress' && f.id === a.id, 1, 'cue a');
  await new Promise((r) => setTimeout(r, 30));
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === a.id, 1, 'played a');
  assert.equal(device.view().phase, 'waiting_tap');
  assert.deepEqual(device.held, [b.id]);
  device.control('advance');
  await relay.frame((f) => f.type === 'control' && f.action === 'advance', 1, 'control advance');
  sched.drain();
  await relay.frame((f) => f.type === 'played' && f.id === b.id, 1, 'played b');

  device.setPace(300, true);
  await relay.frame((f) => f.type === 'pref.changed' && f.prefs.pace_ms === 300, 1, 'pref.changed');
  device.setAdvance('auto', true);
  await relay.frame((f) => f.type === 'pref.changed' && f.prefs.advance === 'auto', 1, 'pref.changed advance');
});

test('stop, replay word, skip and replay operate the current utterance', async () => {
  const { relay, sched, device, transport, vibrations } = await rig();
  transport.connect();
  await relay.count(1);
  relay.ack();
  const a = utt({ words: ['one', 'two', 'three'] });
  relay.send({ type: 'utterance.open', utterance: a });
  await relay.frame((f) => f.type === 'progress' && f.id === a.id, 1, 'cue');
  sched.runUntil(sched.now + 800); // into word 0
  device.control('stop');
  assert.equal(vibrations.at(-1), 0);
  assert.equal(device.view().phase, 'stopped');
  const n = vibrations.length;
  sched.runUntil(sched.now + 5000);
  assert.equal(vibrations.length, n, 'stopped means silent');
  device.control('skip'); // resumes at word 1
  await relay.frame((f) => f.type === 'progress' && f.phase === 'word' && f.word_index === 1, 1, 'word 1');
  device.control('replay_word');
  sched.drain();
  await relay.frame((f) => f.type === 'played', 1, 'played');
  const words = relay.frames.filter((f) => f.type === 'progress' && f.phase === 'word').map((f) => (f.type === 'progress' ? f.word_index : -1));
  assert.deepEqual(words, [0, 1, 1, 2]);
  const frames = relay.frames.length;
  device.control('replay'); // a local replay of the last played utterance: nothing on the wire but the control
  sched.drain();
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(types(relay.frames.slice(frames)), ['control']);
});

test('ping goes out on the cadence and pong is accepted; relay errors are logged', async () => {
  const { relay, sched, transport, log } = await rig({ pingEveryMs: 20_000 });
  transport.connect();
  await relay.count(1);
  relay.ack();
  sched.runUntil(sched.now + 20_000);
  await relay.frame((f) => f.type === 'ping', 1, 'ping');
  relay.send({ type: 'pong' });
  relay.send({ type: 'error', reason: 'bad_request', detail: 'test' });
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(log.some((l) => l.includes('relay error: bad_request')));
});
