/**
 * Headless device driver: the real `Device` renderer (device.ts) against a
 * relay, from the command line. For integration tests and bench work; it is
 * the same state machine as the page, with the DOM and the vibration motor
 * replaced by JSON lines on stdout.
 *
 *   node dist/device-cli.js --relay ws://127.0.0.1:8787 --key <device key> \
 *       [--profile single_actuator|six_actuator] [--clock instant|real] \
 *       [--utterances N] [--idle-exit MS] [--hidden-once]
 *
 *   --relay       the relay (ws://, wss://, http:// or https://; `/ws` optional). The spec is
 *                 fetched from its `/spec` over HTTP, as the page does.
 *   --key         the device key for `hello`; or
 *   --enroll CODE [--name NAME]   exchange an enroll code for a key first (POST /devices/enroll)
 *   --profile     renderer profile declared in hello (default single_actuator)
 *   --clock       `instant` (default): playback deadlines are jumped, so a 10 s utterance plays in
 *                 milliseconds while `played.started_ms/closed_ms` report the real durations; the
 *                 device's one wait for the relay (the body of a body_pending utterance) runs at
 *                 1/--pace-divisor real time. `real`: wall-clock timers, as on a phone. The
 *                 transport's liveness ping and reconnect backoff are wall-clock in both modes.
 *   --utterances  exit 0 once this many utterances have been played (and the relay has seen it)
 *   --idle-exit   exit 0 after this many real ms with nothing held, nothing playing, nothing arriving
 *   --hidden-once nack `hidden` for the first utterance.open, then reconnect (a fresh hello) after
 *                 --hidden-reconnect-ms (default 250) so the relay's re-offer path is exercised
 *
 * stdout: one JSON object per line, each with `event` and `t` (real ms since start):
 *   spec, enrolled, socket, hello.ack, open, body, cancel, progress, played, nack, error, refused, exit
 * stderr: the wire log (frame types and ids, never message text).
 * Exit codes: 0 done, 1 bad arguments or no spec, 3 the relay refused the device key (4401).
 */
import { WebSocket as WsWebSocket } from 'ws';
import { Device } from './device.ts';
import { Player } from './player.ts';
import { MemoryQueueStore } from './queue.ts';
import { resolveSpec } from './spec.ts';
import type { ProfileName } from './spec.ts';
import { Transport } from './transport.ts';
import { VirtualClock } from './virtual-clock.ts';
import type { TimerApi } from './virtual-clock.ts';
import type { DownFrame, UpFrame } from './wire.ts';

export interface CliArgs {
  relay: string;
  key: string | null;
  enroll: string | null;
  name: string;
  profile: ProfileName;
  clock: 'instant' | 'real';
  paceDivisor: number;
  utterances: number | null;
  idleExitMs: number | null;
  hiddenOnce: boolean;
  hiddenReconnectMs: number;
}

export class UsageError extends Error {}

export function parseArgs(argv: string[]): CliArgs {
  const out: CliArgs = {
    relay: '',
    key: null,
    enroll: null,
    name: 'headless device',
    profile: 'single_actuator',
    clock: 'instant',
    paceDivisor: 100,
    utterances: null,
    idleExitMs: null,
    hiddenOnce: false,
    hiddenReconnectMs: 250,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    const [flag, inline] = a.includes('=') ? (a.split(/=(.*)/s) as [string, string]) : [a, undefined];
    const value = (): string => {
      if (inline !== undefined) return inline;
      const v = argv[++i];
      if (v === undefined) throw new UsageError(`${flag} needs a value`);
      return v;
    };
    const int = (what: string, min: number): number => {
      const n = Number(value());
      if (!Number.isInteger(n) || n < min) throw new UsageError(`${what} needs an integer >= ${min}`);
      return n;
    };
    switch (flag) {
      case '--relay':
        out.relay = value();
        break;
      case '--key':
        out.key = value();
        break;
      case '--enroll':
        out.enroll = value().trim().toUpperCase();
        break;
      case '--name':
        out.name = value();
        break;
      case '--profile': {
        const p = value();
        if (p !== 'six_actuator' && p !== 'single_actuator') throw new UsageError(`unknown profile ${p}`);
        out.profile = p;
        break;
      }
      case '--clock': {
        const c = value();
        if (c !== 'instant' && c !== 'real') throw new UsageError(`--clock is instant or real, not ${c}`);
        out.clock = c;
        break;
      }
      case '--pace-divisor':
        out.paceDivisor = int('--pace-divisor', 1);
        break;
      case '--utterances':
        out.utterances = int('--utterances', 1);
        break;
      case '--idle-exit':
        out.idleExitMs = int('--idle-exit', 1);
        break;
      case '--hidden-once':
        out.hiddenOnce = true;
        break;
      case '--hidden-reconnect-ms':
        out.hiddenReconnectMs = int('--hidden-reconnect-ms', 0);
        break;
      default:
        throw new UsageError(`unknown argument ${a}`);
    }
  }
  if (!out.relay) throw new UsageError('--relay is required');
  if (!out.key && !out.enroll) throw new UsageError('--key or --enroll is required');
  if (out.key && out.key.length < 16) throw new UsageError('--key is at least 16 characters');
  return out;
}

/** `ws://host:port[/prefix][/ws]` or `http://host:port[/prefix]` → the HTTP base and the socket URL. */
export function relayUrls(relay: string): { http: string; ws: string } {
  const u = new URL(relay);
  const secure = u.protocol === 'wss:' || u.protocol === 'https:';
  if (!secure && u.protocol !== 'ws:' && u.protocol !== 'http:') throw new UsageError(`--relay: unsupported scheme ${u.protocol}`);
  const base = u.pathname.replace(/\/ws\/?$/, '').replace(/\/+$/, '');
  return {
    http: `${secure ? 'https' : 'http'}://${u.host}${base}`,
    ws: `${secure ? 'wss' : 'ws'}://${u.host}${base}/ws`,
  };
}

interface Io {
  out: (line: string) => void;
  err: (line: string) => void;
  fetch: typeof fetch;
  WebSocket: typeof WebSocket;
  exit: (code: number) => void;
  onSignal: (fn: () => void) => void;
}

export async function run(args: CliArgs, io: Io): Promise<void> {
  const t0 = performance.now();
  const emit = (event: string, fields: Record<string, unknown> = {}): void => {
    io.out(JSON.stringify({ event, t: Math.round(performance.now() - t0), ...fields }));
  };
  const log = (line: string): void => io.err(line);
  const urls = relayUrls(args.relay);

  // --- the spec, like the page: GET /spec --------------------------------------
  let spec;
  try {
    const res = await io.fetch(`${urls.http}/spec`);
    if (!res.ok) throw new Error(`GET /spec returned ${res.status}`);
    spec = resolveSpec(await res.json());
  } catch (err) {
    emit('exit', { reason: 'no_spec', detail: err instanceof Error ? err.message : String(err) });
    io.exit(1);
    return;
  }
  emit('spec', { version: spec.version, shape: spec.shape, encoding: spec.profiles[args.profile].encoding });

  // --- the key: given, or exchanged for an enroll code -------------------------
  let key = args.key;
  if (!key) {
    const res = await io.fetch(`${urls.http}/devices/enroll`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ code: args.enroll, profile: args.profile, name: args.name }),
    });
    const body = (await res.json().catch(() => ({}))) as { device?: unknown; device_key?: unknown; reason?: unknown };
    if (!res.ok || typeof body.device_key !== 'string' || typeof body.device !== 'string') {
      emit('exit', { reason: 'enroll_failed', status: res.status, relay_reason: body.reason ?? null });
      io.exit(1);
      return;
    }
    key = body.device_key;
    emit('enrolled', { device: body.device, device_key: key });
  }

  // --- clocks ------------------------------------------------------------------
  const realTimers: TimerApi = {
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
  };
  const vc = args.clock === 'instant' ? new VirtualClock(args.paceDivisor) : null;
  const now = vc ? vc.clock : (): number => performance.now();
  const playTimers = vc ? vc.instant : realTimers;
  const waitTimers = vc ? vc.paced : realTimers;

  // --- the device --------------------------------------------------------------
  let transport: Transport | null = null;
  let played = 0;
  let finishing = false;
  let hiddenNow = false;
  let hiddenUsed = false;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  const finish = (reason: string, code = 0): void => {
    if (finishing) return;
    finishing = true;
    if (idleTimer) clearTimeout(idleTimer);
    emit('exit', { reason, played });
    transport?.close();
    vc?.dispose();
    io.exit(code);
  };

  const touchIdle = (): void => {
    if (args.idleExitMs === null || finishing) return;
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      idleTimer = null;
      const v = device.view();
      if (v.current === null && v.queue_depth === 0 && !v.announcing) finish('idle');
      else touchIdle();
    }, args.idleExitMs);
  };

  const player = new Player({ now, setTimeout: playTimers.setTimeout, clearTimeout: playTimers.clearTimeout, vibrate: () => undefined });
  const device = new Device({
    spec,
    profile: args.profile,
    player,
    store: new MemoryQueueStore(),
    now,
    setTimeout: waitTimers.setTimeout,
    clearTimeout: waitTimers.clearTimeout,
    isHidden: () => hiddenNow,
    log,
    send: (f: UpFrame) => {
      touchIdle();
      switch (f.type) {
        case 'progress':
          emit('progress', { id: f.id, phase: f.phase, word_index: f.word_index ?? null, clock_ms: Math.round(now()) });
          break;
        case 'played':
          emit('played', { id: f.id, started_ms: f.started_ms, closed_ms: f.closed_ms });
          break;
        case 'nack':
          emit('nack', { id: f.id, reason: f.reason });
          break;
        default:
          break;
      }
      transport?.send(f);
      if (f.type === 'played') {
        played += 1;
        if (args.utterances !== null && played >= args.utterances && !finishing) {
          // a pong proves the relay applied everything sent before it, the played frame included
          transport?.send({ type: 'ping' });
          setTimeout(() => finish('played'), 2000); // if no pong comes, leave anyway
        }
      }
    },
  });

  const onFrame = (f: DownFrame): void => {
    touchIdle();
    switch (f.type) {
      case 'hello.ack':
        emit('hello.ack', { wearer: f.wearer, device: f.device, spec_version: f.spec_version, prefs: f.prefs, resend: (f.resend ?? []).map((u) => u.id) });
        for (const u of f.resend ?? []) emit('open', { via: 'resend', id: u.id, kind: u.kind, words: u.words, body_pending: u.body_pending, prefix: u.prefix ?? null, source: u.source ?? 'sender', label: u.from.label ?? null });
        break;
      case 'utterance.open': {
        const u = f.utterance;
        emit('open', { via: 'open', id: u.id, kind: u.kind, words: u.words, body_pending: u.body_pending, prefix: u.prefix ?? null, source: u.source ?? 'sender', label: u.from.label ?? null });
        break;
      }
      case 'utterance.body':
        emit('body', { id: f.id, words: f.words ?? [], source: f.source ?? 'live', error: f.error ?? null });
        break;
      case 'utterance.cancel':
        emit('cancel', { id: f.id, reason: f.reason });
        break;
      case 'error':
        emit('error', { reason: f.reason, detail: f.detail ?? '' });
        break;
      case 'pong':
        if (args.utterances !== null && played >= args.utterances) finish('played');
        break;
      default:
        break;
    }
    const opens = f.type === 'utterance.open' || (f.type === 'hello.ack' && (f.resend?.length ?? 0) > 0);
    if (args.hiddenOnce && !hiddenUsed && opens) {
      // the page was hidden exactly when the relay offered this: refuse it, then "become visible" and re-hello
      hiddenUsed = true;
      hiddenNow = true;
      device.handleFrame(f);
      hiddenNow = false;
      setTimeout(() => {
        if (!finishing) {
          emit('socket', { status: 'reconnecting', detail: 'visible again after a hidden nack' });
          transport?.reconnect();
        }
      }, args.hiddenReconnectMs);
      return;
    }
    device.handleFrame(f);
  };

  const deviceKey = key;
  transport = new Transport({
    url: urls.ws,
    WebSocket: io.WebSocket,
    makeHello: () => device.hello(deviceKey),
    onFrame,
    onStatus: (status, detail) => {
      if (!finishing) emit('socket', { status, detail });
    },
    onClose: (code) => {
      if (code === 4401 || code === 4400) {
        emit('refused', { code });
        finish('refused', 3);
      }
    },
    log,
    setTimeout: realTimers.setTimeout,
    clearTimeout: realTimers.clearTimeout,
  });
  io.onSignal(() => finish('signal'));
  touchIdle();
  transport.connect();
}

const isMain = typeof process !== 'undefined' && process.argv[1] !== undefined && /device-cli\.(?:ts|js|mjs|cjs)$/.test(process.argv[1]);
if (isMain) {
  let args: CliArgs;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`device-cli: ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(1);
  }
  const io: Io = {
    out: (line) => process.stdout.write(line + '\n'),
    err: (line) => process.stderr.write(line + '\n'),
    fetch: (input, init) => fetch(input, init),
    WebSocket: WsWebSocket as unknown as typeof WebSocket,
    exit: (code) => {
      // let stdout drain before the process goes
      process.exitCode = code;
      setTimeout(() => process.exit(code), 20);
    },
    onSignal: (fn) => {
      process.on('SIGINT', fn);
      process.on('SIGTERM', fn);
    },
  };
  run(args, io).catch((err: unknown) => {
    process.stderr.write(`device-cli: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`);
    process.exit(1);
  });
}
