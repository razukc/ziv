/**
 * The page: wiring between the DOM (index.html), the device, the transport and
 * the environment. Everything the browser provides is injected through
 * `AppEnv` so the page mounts under happy-dom in tests.
 *
 * This page is a foreground renderer and operator view: a browser vibrates only
 * a visible page, so it says so, refuses to play while hidden, and reports that
 * to the relay (docs/ARCHITECTURE.md §5.4).
 */
import { Device } from './device.ts';
import type { DeviceView } from './device.ts';
import { Player } from './player.ts';
import type { QueueStore } from './queue.ts';
import { resolveSpec } from './spec.ts';
import type { ResolvedSpec } from './spec.ts';
import { Transport } from './transport.ts';
import type { TransportStatus } from './transport.ts';
import { composeWords } from './words.ts';

export interface AppEnv {
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  WebSocket: typeof WebSocket;
  storage: Storage | null;
  now: () => number;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  /** null when the browser has no Vibration API: the page is then an operator view only */
  vibrate: ((ms: number) => void) | null;
  openStore: () => Promise<QueueStore>;
  isHidden: () => boolean;
  onVisibility: (cb: (hidden: boolean) => void) => void;
  defaultRelayUrl: string;
}

export interface App {
  readonly device: Device | null;
  readonly transport: Transport | null;
  readonly spec: ResolvedSpec | null;
  readonly logLines: readonly string[];
  start(): Promise<void>;
  enroll(): Promise<void>;
  sendCompose(): void;
  log(line: string): void;
}

export const PROFILE = 'single_actuator' as const;
export const LOG_CAP = 100;
const KEYS = { relay: 'ziv.relay_url', key: 'ziv.device_key', id: 'ziv.device_id', name: 'ziv.device_name' };

export function wsUrlFor(relayUrl: string): string {
  const u = new URL(relayUrl);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = `${u.pathname.replace(/\/$/, '')}/ws`;
  u.search = '';
  u.hash = '';
  return u.toString();
}

export function httpUrlFor(relayUrl: string, path: string): string {
  const u = new URL(relayUrl);
  u.pathname = `${u.pathname.replace(/\/$/, '')}${path}`;
  u.search = '';
  u.hash = '';
  return u.toString();
}

export function mountApp(doc: Document, env: AppEnv): App {
  const $ = <T extends HTMLElement>(id: string): T => {
    const el = doc.getElementById(id);
    if (!el) throw new Error(`index.html lacks #${id}`);
    return el as T;
  };
  const startBtn = $<HTMLButtonElement>('start');
  const relayInput = $<HTMLInputElement>('relay-url');
  const keyInput = $<HTMLInputElement>('device-key');
  const codeInput = $<HTMLInputElement>('enroll-code');
  const nameInput = $<HTMLInputElement>('device-name');
  const enrollBtn = $<HTMLButtonElement>('enroll');
  const enrollMsg = $<HTMLElement>('enroll-msg');
  const statusEl = $<HTMLElement>('status');
  const phaseLive = $<HTMLElement>('phase-live');
  const fromEl = $<HTMLElement>('from');
  const wordsEl = $<HTMLElement>('words');
  const controls = {
    stop: $<HTMLButtonElement>('ctl-stop'),
    replay: $<HTMLButtonElement>('ctl-replay'),
    replay_word: $<HTMLButtonElement>('ctl-replay-word'),
    skip: $<HTMLButtonElement>('ctl-skip'),
    advance: $<HTMLButtonElement>('ctl-advance'),
  } as const;
  const pace = $<HTMLInputElement>('pace');
  const paceOut = $<HTMLElement>('pace-out');
  const advanceTap = $<HTMLInputElement>('advance-tap');
  const historyOn = $<HTMLInputElement>('history-on');
  const historyList = $<HTMLOListElement>('history');
  const historySection = $<HTMLElement>('history-section');
  const compose = $<HTMLInputElement>('compose');
  const composeReply = $<HTMLInputElement>('compose-reply');
  const composeSend = $<HTMLButtonElement>('compose-send');
  const composeMsg = $<HTMLElement>('compose-msg');
  const logEl = $<HTMLElement>('log');
  const vibNote = $<HTMLElement>('vibrate-note');

  const logLines: string[] = [];
  let device: Device | null = null;
  let transport: Transport | null = null;
  let spec: ResolvedSpec | null = null;
  let conn: TransportStatus = 'idle';
  let lastView: DeviceView | null = null;
  let lastAnnounced = '';
  let starting = false;
  /** the device refused an utterance because the page was hidden: a fresh hello asks for it back */
  let refusedWhileHidden = false;

  const stored = (k: string): string | null => {
    try {
      return env.storage?.getItem(k) ?? null;
    } catch {
      return null;
    }
  };
  const store = (k: string, v: string): void => {
    try {
      env.storage?.setItem(k, v);
    } catch {
      /* storage may be unavailable; the page still works for this load */
    }
  };

  function log(line: string): void {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    logLines.push(`${hh}:${mm}:${ss} ${line}`);
    while (logLines.length > LOG_CAP) logLines.shift();
    logEl.textContent = logLines.join('\n');
  }

  function announce(text: string): void {
    if (text === lastAnnounced) return;
    lastAnnounced = text;
    phaseLive.textContent = text;
  }

  function phaseText(v: DeviceView | null): string {
    if (!v) return 'not started';
    const cur = v.current;
    switch (v.phase) {
      case 'idle':
        return v.queue_depth ? 'idle' : 'idle, nothing waiting';
      case 'waiting_tap':
        return `waiting for your tap, ${v.queue_depth} waiting`;
      case 'stopped':
        return 'stopped';
      case 'prefix':
        return 'name mark';
      case 'tail':
        return 'name mark tail';
      case 'cue':
        return `cue: ${cur?.kind ?? ''}`;
      case 'working':
        return 'working, waiting for the words';
      case 'cell':
        return cur && cur.word_index !== null ? `word ${cur.word_index + 1} of ${cur.words.length}: ${cur.words[cur.word_index] ?? ''}` : 'word';
      case 'error':
        return 'error: no words came';
      case 'close':
        return 'end of message';
    }
  }

  function renderStatus(): void {
    const parts: string[] = [];
    parts.push(conn === 'open' ? 'connected' : conn === 'connecting' ? 'connecting' : conn === 'closed' ? 'disconnected' : 'not connected');
    if (spec) parts.push(`spec v${spec.version}${spec.shape === 'v3-fallback' ? ' (v3 fallback)' : ''}`);
    if (lastView) parts.push(`queue ${lastView.queue_depth}`);
    parts.push(phaseText(lastView));
    if (lastView?.announcing) parts.push(`announcing ${lastView.announcing}`);
    statusEl.textContent = parts.join(' · ');
  }

  function renderWords(v: DeviceView): void {
    wordsEl.replaceChildren();
    const cur = v.current;
    fromEl.textContent = cur ? `${cur.kind}${cur.label ? ` from ${cur.label}` : ''}` : '';
    if (!cur) {
      wordsEl.textContent = v.phase === 'waiting_tap' ? 'Tap Advance for the next message.' : '';
      return;
    }
    if (cur.words.length === 0) {
      wordsEl.textContent = cur.body_pending ? 'working…' : '';
      return;
    }
    cur.words.forEach((w, wi) => {
      const wordEl = doc.createElement('span');
      wordEl.className = 'word';
      if (wi === cur.word_index) wordEl.classList.add('current');
      for (let li = 0; li < w.length; li++) {
        const l = doc.createElement('span');
        l.className = 'letter';
        l.textContent = w[li] ?? '';
        if (wi === cur.word_index && li === cur.letter_index) {
          l.classList.add('active');
          l.setAttribute('aria-current', 'true');
        }
        wordEl.appendChild(l);
      }
      wordsEl.appendChild(wordEl);
      if (wi < cur.words.length - 1) wordsEl.appendChild(doc.createTextNode(' '));
    });
  }

  function renderHistory(v: DeviceView): void {
    historySection.hidden = !v.prefs.history;
    historyList.replaceChildren();
    for (const h of v.history.slice().reverse()) {
      const li = doc.createElement('li');
      li.textContent = `${h.kind}${h.label ? ` from ${h.label}` : ''}: ${h.words.join(' ')}`;
      historyList.appendChild(li);
    }
  }

  function renderControls(v: DeviceView | null): void {
    const on = v !== null && conn !== 'idle';
    const playing = on && v !== null && v.current !== null;
    controls.stop.disabled = !playing;
    controls.replay.disabled = !on || (v !== null && v.current === null && v.last_acked === null);
    controls.replay_word.disabled = !playing;
    controls.skip.disabled = !playing;
    controls.advance.disabled = !on;
    composeSend.disabled = conn !== 'open';
  }

  function onView(v: DeviceView): void {
    lastView = v;
    const text = phaseText(v);
    if (v.phase !== 'idle' || v.queue_depth === 0) announce(text);
    renderStatus();
    renderWords(v);
    renderHistory(v);
    renderControls(v);
    if (pace.value !== String(v.prefs.pace_ms)) {
      pace.value = String(v.prefs.pace_ms);
      paceOut.textContent = `${v.prefs.pace_ms} ms`;
    }
    advanceTap.checked = v.prefs.advance === 'tap';
    historyOn.checked = v.prefs.history;
  }

  function refreshStartState(): void {
    const hasKey = keyInput.value.trim().length >= 16;
    startBtn.disabled = starting || device !== null || !hasKey;
    startBtn.textContent = device ? 'Started' : hasKey ? 'Start' : 'Start (enroll first)';
  }

  async function start(): Promise<void> {
    if (device || starting) return;
    const relayUrl = relayInput.value.trim() || env.defaultRelayUrl;
    const key = keyInput.value.trim();
    if (key.length < 16) {
      enrollMsg.textContent = 'A device key (at least 16 characters) is needed before starting.';
      return;
    }
    starting = true;
    refreshStartState();
    store(KEYS.relay, relayUrl);
    store(KEYS.key, key);
    // The tap that got us here is the user activation the Vibration API needs.
    env.vibrate?.(0);
    try {
      const res = await env.fetch(httpUrlFor(relayUrl, '/spec'));
      if (!res.ok) throw new Error(`GET /spec returned ${res.status}`);
      spec = resolveSpec(await res.json());
    } catch (err) {
      log(`spec not loaded: ${err instanceof Error ? err.message : String(err)}`);
      statusEl.textContent = `could not load the timing spec from ${relayUrl}`;
      starting = false;
      refreshStartState();
      return;
    }
    log(`spec v${spec.version} (${spec.shape}); single_actuator cells are ${spec.profiles.single_actuator.encoding}`);
    pace.min = String(spec.cell_gap_min_ms);
    pace.max = String(spec.cell_gap_max_ms);
    pace.step = String(spec.cell_gap_step_ms);
    pace.disabled = false;
    advanceTap.disabled = false;
    historyOn.disabled = false;

    const qstore = await env.openStore();
    log(`queue persisted in ${qstore.kind}`);
    const player = new Player({
      now: env.now,
      setTimeout: env.setTimeout,
      clearTimeout: env.clearTimeout,
      vibrate: env.vibrate ?? (() => undefined),
    });
    const dev = new Device({
      spec,
      profile: PROFILE,
      player,
      store: qstore,
      now: env.now,
      setTimeout: env.setTimeout,
      clearTimeout: env.clearTimeout,
      send: (f) => {
        if (f.type === 'nack' && f.reason === 'hidden') refusedWhileHidden = true;
        transport?.send(f);
      },
      isHidden: env.isHidden,
      log,
      onChange: onView,
    });
    await dev.restore();
    device = dev;
    env.onVisibility((hidden) => {
      log(hidden ? 'page hidden: playback stopped and refused' : 'page visible again');
      dev.onVisibility(hidden);
      if (!hidden && refusedWhileHidden) {
        // the relay holds what this page refused as pending and waits for this device's next hello
        refusedWhileHidden = false;
        transport?.reconnect();
      }
    });
    transport = new Transport({
      url: wsUrlFor(relayUrl),
      WebSocket: env.WebSocket,
      makeHello: () => dev.hello(key),
      onFrame: (f) => dev.handleFrame(f),
      onStatus: (s, detail) => {
        conn = s;
        log(`socket ${s}${detail ? `: ${detail}` : ''}`);
        renderStatus();
        renderControls(lastView);
      },
      log,
      setTimeout: env.setTimeout,
      clearTimeout: env.clearTimeout,
    });
    transport.connect();
    starting = false;
    refreshStartState();
    onView(dev.view());
  }

  async function enroll(): Promise<void> {
    const relayUrl = relayInput.value.trim() || env.defaultRelayUrl;
    const code = codeInput.value.trim().toUpperCase();
    const name = nameInput.value.trim() || 'web renderer';
    if (!/^[0-9A-Z]{6,12}$/.test(code)) {
      enrollMsg.textContent = 'An enroll code is 6 to 12 letters or digits.';
      return;
    }
    enrollBtn.disabled = true;
    enrollMsg.textContent = 'Enrolling…';
    try {
      const res = await env.fetch(httpUrlFor(relayUrl, '/devices/enroll'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ code, profile: PROFILE, name }),
      });
      if (!res.ok) throw new Error(`relay answered ${res.status}`);
      const body = (await res.json()) as { device?: unknown; device_key?: unknown };
      if (typeof body.device_key !== 'string' || typeof body.device !== 'string') throw new Error('no device key in the answer');
      keyInput.value = body.device_key;
      store(KEYS.key, body.device_key);
      store(KEYS.id, body.device);
      store(KEYS.name, name);
      store(KEYS.relay, relayUrl);
      enrollMsg.textContent = `Enrolled as ${body.device}. The key is stored in this browser.`;
      log(`enrolled as ${body.device}`);
    } catch (err) {
      enrollMsg.textContent = `Enrollment failed: ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      enrollBtn.disabled = false;
      refreshStartState();
    }
  }

  function sendCompose(): void {
    const r = composeWords(compose.value);
    if (!r.ok) {
      composeMsg.textContent = r.reason;
      return;
    }
    if (!transport || transport.status !== 'open') {
      composeMsg.textContent = 'Not connected to the relay.';
      return;
    }
    const inReplyTo = composeReply.checked ? (lastView?.last_acked ?? null) : null;
    transport.send({ type: 'input.text', words: r.words, in_reply_to: inReplyTo });
    composeMsg.textContent = `Sent: ${r.words.join(' ')}`;
    compose.value = '';
  }

  // --- static wiring ------------------------------------------------------------

  relayInput.value = stored(KEYS.relay) ?? env.defaultRelayUrl;
  keyInput.value = stored(KEYS.key) ?? '';
  nameInput.value = stored(KEYS.name) ?? '';
  if (!env.vibrate) {
    vibNote.textContent = 'This browser has no Vibration API: the page runs as an operator view and plays nothing on the skin.';
  }
  keyInput.addEventListener('input', refreshStartState);
  startBtn.addEventListener('click', () => void start());
  enrollBtn.addEventListener('click', () => void enroll());
  for (const [action, btn] of Object.entries(controls) as [keyof typeof controls, HTMLButtonElement][]) {
    btn.addEventListener('click', () => device?.control(action));
  }
  pace.addEventListener('input', () => {
    paceOut.textContent = `${pace.value} ms`;
  });
  pace.addEventListener('change', () => device?.setPace(Number(pace.value), true));
  advanceTap.addEventListener('change', () => device?.setAdvance(advanceTap.checked ? 'tap' : 'auto', true));
  historyOn.addEventListener('change', () => device?.setHistory(historyOn.checked, true));
  composeSend.addEventListener('click', sendCompose);
  compose.addEventListener('keydown', (ev: KeyboardEvent) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      sendCompose();
    }
  });
  pace.disabled = true;
  advanceTap.disabled = true;
  historyOn.disabled = true;
  renderControls(null);
  renderStatus();
  refreshStartState();

  return {
    get device() {
      return device;
    },
    get transport() {
      return transport;
    },
    get spec() {
      return spec;
    },
    logLines,
    start,
    enroll,
    sendCompose,
    log,
  };
}
