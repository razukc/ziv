/**
 * The device side of the wire contract. The truth is ziv/wire.py and the JSON
 * Schemas it emits (schema/device-frames-down.json, schema/device-frames-up.json,
 * schema/utterance.json); these types mirror them field for field. Frames the
 * relay sends are checked structurally on receipt; an unknown type or a missing
 * field is a `WireError`, never a silent pass.
 */

export const WIRE_VERSION = 1;

export type Kind = 'message' | 'reminder' | 'error' | 'system';
export type Profile = 'six_actuator' | 'single_actuator';
export type Advance = 'auto' | 'tap';
export type Late = 'drop' | 'play';
export type PhaseName = 'cue' | 'working' | 'word' | 'close';
export type ControlAction = 'stop' | 'replay' | 'replay_word' | 'skip' | 'advance';

/** Known reasons; the relay may add more, so received reasons stay open strings. */
export type Reason =
  | 'queue_full'
  | 'over_budget'
  | 'unencodable'
  | 'expired'
  | 'spec_mismatch'
  | 'body_timeout'
  | 'hidden'
  | 'muted'
  | 'device_gone'
  | 'failover'
  | 'compose_failed'
  | 'cancelled_by_sender'
  | 'cancelled_by_wearer'
  | 'unauthorized'
  | 'bad_request'
  | 'rate_limited'
  | 'not_found'
  | 'conflict'
  | (string & {});

export interface Prefs {
  pace_ms?: number | null;
  advance?: Advance | null;
  late?: Late | null;
  history?: boolean | null;
}

export interface Prefix {
  mark: string;
  tail: string;
}

export interface Utterance {
  v: 1;
  id: string;
  wearer: string;
  kind: Kind;
  from: { sender: string; label?: string | null };
  prefix?: Prefix | null;
  words: string[];
  body_pending: boolean;
  source?: string;
  not_before?: string | null;
  expires?: string | null;
  spec_version: number;
}

// --- relay -> device -------------------------------------------------------

export interface HelloAck {
  type: 'hello.ack';
  v?: 1;
  wearer: string;
  device: string;
  spec_version: number;
  prefs: Prefs;
  resend?: Utterance[];
}
export interface UtteranceOpen {
  type: 'utterance.open';
  utterance: Utterance;
}
export interface UtteranceBody {
  type: 'utterance.body';
  id: string;
  words?: string[];
  source?: string;
  error?: Reason | null;
}
export interface UtteranceCancel {
  type: 'utterance.cancel';
  id: string;
  reason: Reason;
}
export interface PrefSet {
  type: 'pref.set';
  prefs: Prefs;
}
export interface Pong {
  type: 'pong';
}
export interface ProtocolError {
  type: 'error';
  reason: Reason;
  detail?: string;
}
export type DownFrame = HelloAck | UtteranceOpen | UtteranceBody | UtteranceCancel | PrefSet | Pong | ProtocolError;

// --- device -> relay -------------------------------------------------------

export interface Hello {
  type: 'hello';
  v: 1;
  device_key: string;
  profile: Profile;
  spec_version: number;
  pace_ms?: number | null;
  last_acked?: string | null;
  held?: string[];
}
export interface Progress {
  type: 'progress';
  id: string;
  phase: PhaseName;
  word_index?: number | null;
}
export interface Played {
  type: 'played';
  id: string;
  started_ms: number;
  closed_ms: number;
}
export interface Nack {
  type: 'nack';
  id: string;
  reason: Reason;
}
export interface InputText {
  type: 'input.text';
  words: string[];
  in_reply_to?: string | null;
}
export interface Control {
  type: 'control';
  action: ControlAction;
}
export interface PrefChanged {
  type: 'pref.changed';
  prefs: Prefs;
}
export interface Ping {
  type: 'ping';
}
export type UpFrame = Hello | Progress | Played | Nack | InputText | Control | PrefChanged | Ping;

// --- checks ----------------------------------------------------------------

export const ID_RE = /^[0-9A-Za-z_-]{8,64}$/;
export const WORD_RE = /^[a-z]{1,32}$/;
export const MARK_RE = /^[a-z]{1,8}$/;
export const PATTERN_ID_RE = /^[a-z][a-z0-9-]{0,31}$/;
export const MAX_WORDS = 64;
export const MAX_WORD_LETTERS = 32;
export const KINDS: readonly Kind[] = ['message', 'reminder', 'error', 'system'];

export class WireError extends Error {}

function rec(v: unknown, what: string): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new WireError(`${what}: not an object`);
  return v as Record<string, unknown>;
}

function str(v: unknown, what: string): string {
  if (typeof v !== 'string') throw new WireError(`${what}: not a string`);
  return v;
}

function id(v: unknown, what: string): string {
  const s = str(v, what);
  if (!ID_RE.test(s)) throw new WireError(`${what}: not an utterance id`);
  return s;
}

function words(v: unknown, what: string): string[] {
  if (v === undefined || v === null) return [];
  if (!Array.isArray(v)) throw new WireError(`${what}: not a list`);
  if (v.length > MAX_WORDS) throw new WireError(`${what}: more than ${MAX_WORDS} words`);
  return v.map((w, i) => {
    const s = str(w, `${what}[${i}]`);
    if (!WORD_RE.test(s)) throw new WireError(`${what}[${i}]: not a word a–z`);
    return s;
  });
}

function prefs(v: unknown, what: string): Prefs {
  const o = rec(v, what);
  const out: Prefs = {};
  if (o.pace_ms !== undefined && o.pace_ms !== null) {
    if (typeof o.pace_ms !== 'number' || !Number.isInteger(o.pace_ms)) throw new WireError(`${what}.pace_ms: not an integer`);
    out.pace_ms = o.pace_ms;
  }
  if (o.advance !== undefined && o.advance !== null) {
    if (o.advance !== 'auto' && o.advance !== 'tap') throw new WireError(`${what}.advance: not auto|tap`);
    out.advance = o.advance;
  }
  if (o.late !== undefined && o.late !== null) {
    if (o.late !== 'drop' && o.late !== 'play') throw new WireError(`${what}.late: not drop|play`);
    out.late = o.late;
  }
  if (o.history !== undefined && o.history !== null) {
    if (typeof o.history !== 'boolean') throw new WireError(`${what}.history: not a boolean`);
    out.history = o.history;
  }
  return out;
}

/** Validate an utterance against schema/utterance.json and fill its defaults. */
export function checkUtterance(v: unknown): Utterance {
  const o = rec(v, 'utterance');
  if (o.v !== undefined && o.v !== 1) throw new WireError('utterance.v: not 1');
  const from = rec(o.from, 'utterance.from');
  const kind = str(o.kind, 'utterance.kind');
  if (!(KINDS as readonly string[]).includes(kind)) throw new WireError(`utterance.kind: unknown kind ${JSON.stringify(kind)}`);
  let prefix: Prefix | null = null;
  if (o.prefix !== undefined && o.prefix !== null) {
    const p = rec(o.prefix, 'utterance.prefix');
    const mark = str(p.mark, 'utterance.prefix.mark');
    const tail = str(p.tail, 'utterance.prefix.tail');
    if (!MARK_RE.test(mark)) throw new WireError('utterance.prefix.mark: not a mark a–z');
    if (!PATTERN_ID_RE.test(tail)) throw new WireError('utterance.prefix.tail: not a pattern id');
    prefix = { mark, tail };
  }
  const ws = words(o.words, 'utterance.words');
  const body_pending = o.body_pending === undefined ? false : o.body_pending;
  if (typeof body_pending !== 'boolean') throw new WireError('utterance.body_pending: not a boolean');
  if (!body_pending && ws.length === 0) throw new WireError('utterance: needs words unless body_pending');
  if (typeof o.spec_version !== 'number' || !Number.isInteger(o.spec_version) || o.spec_version < 1) {
    throw new WireError('utterance.spec_version: not a positive integer');
  }
  const out: Utterance = {
    v: 1,
    id: id(o.id, 'utterance.id'),
    wearer: str(o.wearer, 'utterance.wearer'),
    kind: kind as Kind,
    from: { sender: str(from.sender, 'utterance.from.sender'), label: typeof from.label === 'string' ? from.label : null },
    prefix,
    words: ws,
    body_pending,
    source: typeof o.source === 'string' ? o.source : 'sender',
    not_before: typeof o.not_before === 'string' ? o.not_before : null,
    expires: typeof o.expires === 'string' ? o.expires : null,
    spec_version: o.spec_version,
  };
  return out;
}

/** Parse one text frame from the relay. */
export function parseDownFrame(text: string): DownFrame {
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch {
    throw new WireError('frame: not JSON');
  }
  const o = rec(v, 'frame');
  const type = str(o.type, 'frame.type');
  switch (type) {
    case 'hello.ack': {
      if (typeof o.spec_version !== 'number') throw new WireError('hello.ack.spec_version: not a number');
      const resendRaw = o.resend === undefined || o.resend === null ? [] : o.resend;
      if (!Array.isArray(resendRaw)) throw new WireError('hello.ack.resend: not a list');
      return {
        type,
        wearer: str(o.wearer, 'hello.ack.wearer'),
        device: str(o.device, 'hello.ack.device'),
        spec_version: o.spec_version,
        prefs: prefs(o.prefs ?? {}, 'hello.ack.prefs'),
        resend: resendRaw.map((u) => checkUtterance(u)),
      };
    }
    case 'utterance.open':
      return { type, utterance: checkUtterance(o.utterance) };
    case 'utterance.body': {
      const ws = words(o.words, 'utterance.body.words');
      const error = o.error === undefined || o.error === null ? null : str(o.error, 'utterance.body.error');
      if ((ws.length > 0) === (error !== null)) throw new WireError('utterance.body: words or error, exactly one');
      return { type, id: id(o.id, 'utterance.body.id'), words: ws, source: typeof o.source === 'string' ? o.source : 'live', error };
    }
    case 'utterance.cancel':
      return { type, id: id(o.id, 'utterance.cancel.id'), reason: str(o.reason, 'utterance.cancel.reason') };
    case 'pref.set':
      return { type, prefs: prefs(o.prefs, 'pref.set.prefs') };
    case 'pong':
      return { type };
    case 'error':
      return { type, reason: str(o.reason, 'error.reason'), detail: typeof o.detail === 'string' ? o.detail : '' };
    default:
      throw new WireError(`frame.type: unknown ${JSON.stringify(type)}`);
  }
}

/** A content-free one-liner for the wire log (never message text). */
export function describe(frame: DownFrame | UpFrame): string {
  switch (frame.type) {
    case 'hello':
      return `hello profile=${frame.profile} spec=v${frame.spec_version} pace=${frame.pace_ms ?? '-'} last_acked=${frame.last_acked ?? '-'} held=${frame.held?.length ?? 0}`;
    case 'hello.ack':
      return `hello.ack wearer=${frame.wearer} device=${frame.device} spec=v${frame.spec_version} resend=${frame.resend?.length ?? 0}`;
    case 'utterance.open': {
      const u = frame.utterance;
      return `utterance.open id=${u.id} kind=${u.kind} words=${u.words.length}${u.body_pending ? ' body_pending' : ''}${u.prefix ? ` prefix=${u.prefix.mark}/${u.prefix.tail}` : ''}`;
    }
    case 'utterance.body':
      return `utterance.body id=${frame.id} ${frame.error ? `error=${frame.error}` : `words=${frame.words?.length ?? 0}`}`;
    case 'utterance.cancel':
      return `utterance.cancel id=${frame.id} reason=${frame.reason}`;
    case 'pref.set':
      return `pref.set ${JSON.stringify(frame.prefs)}`;
    case 'pref.changed':
      return `pref.changed ${JSON.stringify(frame.prefs)}`;
    case 'progress':
      return `progress id=${frame.id} ${frame.phase}${frame.word_index !== undefined && frame.word_index !== null ? ` ${frame.word_index}` : ''}`;
    case 'played':
      return `played id=${frame.id} took=${frame.closed_ms - frame.started_ms}ms`;
    case 'nack':
      return `nack id=${frame.id} reason=${frame.reason}`;
    case 'input.text':
      return `input.text words=${frame.words.length}${frame.in_reply_to ? ` in_reply_to=${frame.in_reply_to}` : ''}`;
    case 'control':
      return `control ${frame.action}`;
    case 'error':
      return `error reason=${frame.reason}${frame.detail ? ` ${frame.detail}` : ''}`;
    case 'ping':
    case 'pong':
      return frame.type;
  }
}
