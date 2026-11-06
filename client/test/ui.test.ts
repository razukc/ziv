// The page under happy-dom: mounting, the start flow against a fake fetch and
// a fake WebSocket, compose normalisation in the UI, the active letter, and the
// hidden-page refusal. The device clock is a fake scheduler.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { Window } from 'happy-dom';
import { mountApp, wsUrlFor, httpUrlFor } from '../src/app.ts';
import type { App } from '../src/app.ts';
import { MemoryQueueStore } from '../src/queue.ts';
import type { UpFrame } from '../src/wire.ts';
import { FakeScheduler, here, rawSpec, utt } from './helpers.ts';

class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  readonly url: string;
  readyState = 0;
  sent: UpFrame[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  send(text: string): void {
    this.sent.push(JSON.parse(text) as UpFrame);
  }
  close(): void {
    this.readyState = 3;
    this.onclose?.({ code: 1000 });
  }
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

function bodyOf(html: string): string {
  const m = /<body>([\s\S]*)<\/body>/.exec(html);
  return (m?.[1] ?? '').replace(/<script[\s\S]*?<\/script>/g, '');
}

interface Mounted {
  app: App;
  win: Window;
  doc: Document;
  sched: FakeScheduler;
  vibrations: number[];
  hidden: { value: boolean };
  visibility: ((hidden: boolean) => void)[];
  fetches: string[];
}

function mount(): Mounted {
  const win = new Window({ url: 'http://relay.test/' });
  const doc = win.document as unknown as Document;
  doc.body.innerHTML = bodyOf(readFileSync(resolve(here, '..', 'index.html'), 'utf8'));
  const sched = new FakeScheduler();
  const vibrations: number[] = [];
  const hidden = { value: false };
  const visibility: ((hidden: boolean) => void)[] = [];
  const fetches: string[] = [];
  const storage = new Map<string, string>();
  const app = mountApp(doc, {
    fetch: async (input) => {
      fetches.push(input);
      if (input.endsWith('/spec')) return new Response(JSON.stringify(rawSpec()), { status: 200, headers: { 'content-type': 'application/json' } });
      if (input.endsWith('/devices/enroll')) return new Response(JSON.stringify({ device: 'd_web', device_key: 'K'.repeat(40) }), { status: 200 });
      return new Response('nope', { status: 404 });
    },
    WebSocket: FakeSocket as unknown as typeof WebSocket,
    storage: {
      getItem: (k: string) => storage.get(k) ?? null,
      setItem: (k: string, v: string) => void storage.set(k, v),
      removeItem: (k: string) => void storage.delete(k),
      clear: () => storage.clear(),
      key: () => null,
      length: 0,
    } as Storage,
    now: sched.clock,
    setTimeout: sched.setTimeout,
    clearTimeout: sched.clearTimeout,
    vibrate: (ms) => vibrations.push(ms),
    openStore: async () => new MemoryQueueStore(),
    isHidden: () => hidden.value,
    onVisibility: (cb) => visibility.push(cb),
    defaultRelayUrl: 'http://relay.test',
  });
  return { app, win, doc, sched, vibrations, hidden, visibility, fetches };
}

const $ = <T extends HTMLElement>(doc: Document, id: string): T => doc.getElementById(id) as T;

test('relay URLs derive the socket and HTTP endpoints', () => {
  assert.equal(wsUrlFor('https://relay.example/'), 'wss://relay.example/ws');
  assert.equal(wsUrlFor('http://127.0.0.1:8787'), 'ws://127.0.0.1:8787/ws');
  assert.equal(httpUrlFor('https://relay.example/base/', '/spec'), 'https://relay.example/base/spec');
});

test('the page mounts with the visibility note, labelled controls, and Start disabled until a key is present', () => {
  const { doc } = mount();
  assert.match($(doc, 'vibrate-note').textContent ?? '', /vibrates only while it is visible/);
  const start = $<HTMLButtonElement>(doc, 'start');
  assert.equal(start.disabled, true);
  for (const id of ['relay-url', 'device-key', 'pace', 'compose', 'advance-tap', 'history-on']) {
    assert.ok(doc.querySelector(`label[for="${id}"]`), `#${id} has a label`);
  }
  assert.equal($(doc, 'phase-live').getAttribute('aria-live'), 'polite');
  const key = $<HTMLInputElement>(doc, 'device-key');
  key.value = 'K'.repeat(32);
  key.dispatchEvent(new (doc.defaultView as unknown as typeof globalThis).Event('input'));
  assert.equal(start.disabled, false);
});

test('start fetches the spec, connects with hello first, and shows status; compose refuses non-letters and spells digits', async () => {
  FakeSocket.instances = [];
  const { app, doc, fetches } = mount();
  $<HTMLInputElement>(doc, 'device-key').value = 'K'.repeat(32);
  await app.start();
  assert.ok(fetches.some((f) => f === 'http://relay.test/spec'));
  assert.equal(app.spec?.version, rawSpec().version);
  assert.equal($<HTMLInputElement>(doc, 'pace').min, '250');
  const ws = FakeSocket.instances[0]!;
  assert.equal(ws.url, 'ws://relay.test/ws');
  ws.open();
  assert.equal(ws.sent[0]!.type, 'hello');
  ws.receive({ type: 'hello.ack', wearer: 'w_1', device: 'd_web', spec_version: rawSpec().version, prefs: { advance: 'tap' } });
  assert.match($(doc, 'status').textContent ?? '', /connected · spec v4/);
  assert.equal($<HTMLInputElement>(doc, 'advance-tap').checked, true);

  const compose = $<HTMLInputElement>(doc, 'compose');
  compose.value = 'hi!';
  app.sendCompose();
  assert.match($(doc, 'compose-msg').textContent ?? '', /"!" has no cell/);
  assert.equal(ws.sent.filter((f) => f.type === 'input.text').length, 0);
  compose.value = 'Room 9';
  app.sendCompose();
  const sent = ws.sent.find((f) => f.type === 'input.text');
  assert.deepEqual(sent, { type: 'input.text', words: ['room', 'nine'], in_reply_to: null });
  assert.equal(compose.value, '');
});

test('an open utterance shows its words with the active letter marked; a hidden page refuses with nack hidden', async () => {
  FakeSocket.instances = [];
  const { app, doc, sched, vibrations, hidden, visibility } = mount();
  $<HTMLInputElement>(doc, 'device-key').value = 'K'.repeat(32);
  await app.start();
  const ws = FakeSocket.instances[0]!;
  ws.open();
  ws.receive({ type: 'hello.ack', wearer: 'w_1', device: 'd_web', spec_version: rawSpec().version, prefs: {} });
  const u = utt({ words: ['meds', 'now'] });
  ws.receive({ type: 'utterance.open', utterance: u });
  assert.equal(ws.sent.at(-1)?.type, 'progress');
  sched.runUntil(sched.now + 800); // into the first word
  const active = doc.querySelector('.letter.active');
  assert.ok(active, 'an active letter is marked');
  assert.equal(active?.getAttribute('aria-current'), 'true');
  assert.equal(active?.textContent, 'm');
  assert.match($(doc, 'phase-live').textContent ?? '', /word 1 of 2: meds/);
  assert.ok(vibrations.length > 0);

  hidden.value = true;
  for (const cb of visibility) cb(true);
  const nack = ws.sent.at(-1);
  assert.deepEqual(nack, { type: 'nack', id: u.id, reason: 'hidden' });
  assert.equal(vibrations.at(-1), 0);
  assert.match(app.logLines.at(-2) ?? '', /page hidden/);

  // visible again: the relay holds what this page refused as pending until its next hello, so the
  // page reconnects at once and the fresh hello asks for it back
  assert.equal(FakeSocket.instances.length, 1);
  hidden.value = false;
  for (const cb of visibility) cb(false);
  assert.equal(FakeSocket.instances.length, 2, 'a fresh socket after a hidden nack');
  assert.equal(ws.readyState, 3, 'the old socket was closed');
  const ws2 = FakeSocket.instances[1]!;
  ws2.open();
  assert.equal(ws2.sent[0]?.type, 'hello');
  ws2.receive({ type: 'hello.ack', wearer: 'w_1', device: 'd_web', spec_version: rawSpec().version, prefs: {}, resend: [u] });
  assert.deepEqual(ws2.sent.at(-1), { type: 'progress', id: u.id, phase: 'cue' });
  // once the utterance has played, a plain visibility round trip (nothing refused) does not churn the socket
  sched.runUntil(sched.now + 60_000);
  assert.equal(ws2.sent.filter((f) => f.type === 'played').length, 1);
  for (const cb of visibility) cb(true);
  for (const cb of visibility) cb(false);
  assert.equal(FakeSocket.instances.length, 2);

  const historyOn = $<HTMLInputElement>(doc, 'history-on');
  assert.equal($(doc, 'history-section').hidden, true);
  historyOn.checked = true;
  historyOn.dispatchEvent(new (doc.defaultView as unknown as typeof globalThis).Event('change'));
  assert.equal($(doc, 'history-section').hidden, false);
  assert.equal(ws2.sent.at(-1)?.type, 'pref.changed');
});

test('enrollment posts the code and profile, stores the key, and enables Start', async () => {
  const { app, doc, fetches } = mount();
  $<HTMLInputElement>(doc, 'enroll-code').value = 'abc123';
  $<HTMLInputElement>(doc, 'device-name').value = 'bench';
  await app.enroll();
  assert.ok(fetches.includes('http://relay.test/devices/enroll'));
  assert.equal($<HTMLInputElement>(doc, 'device-key').value, 'K'.repeat(40));
  assert.match($(doc, 'enroll-msg').textContent ?? '', /Enrolled as d_web/);
  assert.equal($<HTMLButtonElement>(doc, 'start').disabled, false);
});
