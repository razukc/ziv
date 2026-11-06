/**
 * The device renderer (docs/ARCHITECTURE.md §5.1) for the `single_actuator`
 * profile: a bounded queue of utterances, exactly one playing at a time, the
 * wearer's controls, and the frames that report it all back to the relay.
 *
 * Everything time-related goes through injected `now`/`setTimeout` and the
 * injected player, so the whole state machine runs under a fake clock.
 *
 * Decisions this class makes that the contract leaves open are marked DECISION.
 */
import { clampPace } from './spec.ts';
import type { ProfileName, ResolvedSpec } from './spec.ts';
import { cueSegment, errorSegments, segments } from './sequencer.ts';
import type { Phase, Segment } from './sequencer.ts';
import type { Player } from './player.ts';
import type { HeldEntry, QueueStore } from './queue.ts';
import type { Advance, ControlAction, DownFrame, Hello, Late, Prefs, Reason, UpFrame, Utterance } from './wire.ts';

export const DEFAULT_QUEUE_CAP = 20;
export const DEFAULT_BODY_TIMEOUT_MS = 20_000;
export const HISTORY_CAP = 20;

export interface DevicePrefs {
  pace_ms: number;
  advance: Advance;
  late: Late;
  history: boolean;
}

export interface HistoryEntry {
  id: string;
  kind: string;
  label: string | null;
  words: string[];
  at: number;
}

export type ViewPhase = 'idle' | 'waiting_tap' | 'stopped' | Phase;

export interface DeviceView {
  phase: ViewPhase;
  current: {
    id: string;
    kind: string;
    label: string | null;
    words: string[];
    word_index: number | null;
    letter_index: number | null;
    body_pending: boolean;
  } | null;
  /** an arrival cue being announced for a queued utterance */
  announcing: string | null;
  queue_depth: number;
  held: string[];
  last_acked: string | null;
  prefs: DevicePrefs;
  history: HistoryEntry[];
}

export interface DeviceDeps {
  spec: ResolvedSpec;
  profile: ProfileName;
  player: Player;
  store: QueueStore;
  now: () => number;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  send: (frame: UpFrame) => void;
  isHidden: () => boolean;
  wallClock?: () => number;
  log?: (line: string) => void;
  onChange?: (view: DeviceView) => void;
  queueCap?: number;
  bodyTimeoutMs?: number;
}

interface Current {
  entry: HeldEntry;
  segs: Segment[];
  idx: number;
  /** when the next segment is due to start, on the device clock */
  cursor: number;
  started_ms: number | null;
  stopped: boolean;
  /** nacked already: play the error pattern and the close for the wearer, report nothing more */
  failed: boolean;
  /** a replay of an already-played utterance: nothing goes on the wire */
  local: boolean;
  workingStartedAt: number | null;
  lastWorkingAt: number | null;
  workingReported: boolean;
  waitTimer: unknown;
}

export class Device {
  readonly prefs: DevicePrefs;
  private readonly d: DeviceDeps;
  private queue: HeldEntry[] = [];
  private lastAcked: string | null = null;
  private lastPlayed: HeldEntry | null = null;
  private cur: Current | null = null;
  private waitingTap = false;
  private pendingCues: HeldEntry[] = [];
  private announcing: HeldEntry | null = null;
  private stepAfterCue = false;
  private historyList: HistoryEntry[] = [];

  constructor(deps: DeviceDeps) {
    this.d = deps;
    this.prefs = { pace_ms: deps.spec.cell_gap_default_ms, advance: 'auto', late: 'drop', history: false };
  }

  // --- lifecycle -------------------------------------------------------------

  /** Load what a previous page load held. Cues replay at their turn. */
  async restore(): Promise<void> {
    const snap = await this.d.store.load();
    this.queue = snap.entries.map((e) => ({ ...e, cued: false }));
    this.lastAcked = snap.last_acked;
    this.emit();
  }

  hello(deviceKey: string): Hello {
    return {
      type: 'hello',
      v: 1,
      device_key: deviceKey,
      profile: this.d.profile,
      spec_version: this.d.spec.version,
      pace_ms: this.prefs.pace_ms,
      last_acked: this.lastAcked,
      held: this.queue.map((e) => e.utt.id),
    };
  }

  /** Play what is held, if idle and allowed to. */
  resume(): void {
    const head = this.queue[0];
    if (!this.cur && !this.waitingTap && head && !this.d.isHidden()) this.begin(head, false);
  }

  get held(): string[] {
    return this.queue.map((e) => e.utt.id);
  }

  get lastAckedId(): string | null {
    return this.lastAcked;
  }

  view(): DeviceView {
    const cur = this.cur;
    let phase: ViewPhase = 'idle';
    let current: DeviceView['current'] = null;
    if (cur) {
      const seg = cur.segs[cur.idx];
      phase = cur.stopped ? 'stopped' : (seg?.phase ?? 'close');
      current = {
        id: cur.entry.utt.id,
        kind: cur.entry.utt.kind,
        label: cur.entry.utt.from.label ?? null,
        words: wordsOf(cur.entry),
        word_index: seg?.phase === 'cell' ? seg.word_index : null,
        letter_index: seg?.phase === 'cell' ? seg.letter_index : null,
        body_pending: cur.entry.body === null && cur.entry.utt.body_pending,
      };
    } else if (this.waitingTap) {
      phase = 'waiting_tap';
    }
    return {
      phase,
      current,
      announcing: this.announcing?.utt.id ?? null,
      queue_depth: this.queue.length,
      held: this.held,
      last_acked: this.lastAcked,
      prefs: { ...this.prefs },
      history: this.historyList.slice(),
    };
  }

  // --- frames from the relay ---------------------------------------------------

  handleFrame(f: DownFrame): void {
    switch (f.type) {
      case 'hello.ack':
        this.applyPrefs(f.prefs);
        if (f.spec_version !== this.d.spec.version) {
          this.log(`relay speaks spec v${f.spec_version}, this device v${this.d.spec.version}: mismatching utterances will be refused`);
        }
        for (const u of f.resend ?? []) this.open(u);
        this.resume();
        break;
      case 'utterance.open':
        this.open(f.utterance);
        break;
      case 'utterance.body':
        this.body(f.id, f.error ? { error: f.error } : { words: f.words ?? [], source: f.source });
        break;
      case 'utterance.cancel':
        this.cancel(f.id, f.reason);
        break;
      case 'pref.set':
        this.applyPrefs(f.prefs);
        break;
      case 'pong':
        break;
      case 'error':
        this.log(`relay error: ${f.reason}${f.detail ? ` (${f.detail})` : ''}`);
        break;
    }
  }

  open(utt: Utterance): void {
    if (utt.spec_version !== this.d.spec.version) {
      this.nack(utt.id, 'spec_mismatch');
      return;
    }
    if (this.d.isHidden()) {
      // DECISION: a hidden page cannot vibrate, so it refuses rather than holds;
      // the relay fails over or resends when the page is visible again.
      this.nack(utt.id, 'hidden');
      return;
    }
    if (utt.id === this.lastAcked || this.queue.some((e) => e.utt.id === utt.id)) {
      this.log(`duplicate ${utt.id} ignored`);
      return;
    }
    if (this.queue.length >= (this.d.queueCap ?? DEFAULT_QUEUE_CAP)) {
      this.nack(utt.id, 'queue_full');
      return;
    }
    const entry: HeldEntry = { utt, body: null, cued: false, received_at: this.wall() };
    this.queue.push(entry);
    this.persist();
    if (this.cur) {
      // announce between cells: at the next segment boundary, or now if the device is silent
      this.pendingCues.push(entry);
      if (this.cur.stopped || this.cur.waitTimer !== null) this.drainCues();
    } else if (this.waitingTap) {
      this.pendingCues.push(entry);
      this.drainCues();
    } else {
      this.begin(entry, false);
    }
    this.emit();
  }

  body(id: string, state: NonNullable<HeldEntry['body']>): void {
    const entry = this.queue.find((e) => e.utt.id === id);
    if (!entry) {
      this.log(`body for ${id}, which this device does not hold; ignored`);
      return;
    }
    entry.body = state;
    this.persist();
    const cur = this.cur;
    if (cur && cur.entry === entry && cur.waitTimer !== null) {
      // waiting in silence between working repeats: go on now
      this.d.clearTimeout(cur.waitTimer);
      cur.waitTimer = null;
      this.step();
    }
    this.emit();
  }

  cancel(id: string, reason: Reason): void {
    this.pendingCues = this.pendingCues.filter((e) => e.utt.id !== id);
    const cur = this.cur;
    if (cur && cur.entry.utt.id === id) {
      this.log(`current ${id} cancelled: ${reason}`);
      this.abandonCurrent();
      this.removeFromQueue(cur.entry);
      this.persist();
      this.afterTurn();
      this.emit();
      return;
    }
    if (this.announcing && this.announcing.utt.id === id) {
      this.d.player.stop();
      this.announcing = null;
    }
    const i = this.queue.findIndex((e) => e.utt.id === id);
    if (i >= 0) {
      this.queue.splice(i, 1);
      this.persist();
    }
    this.emit();
  }

  applyPrefs(p: Prefs): void {
    if (p.pace_ms !== undefined && p.pace_ms !== null) this.setPace(p.pace_ms, false);
    if (p.advance) this.setAdvance(p.advance, false);
    if (p.late) this.setLate(p.late, false);
    if (p.history !== undefined && p.history !== null) this.setHistory(p.history, false);
  }

  // --- the wearer -------------------------------------------------------------

  setPace(ms: number, fromWearer: boolean): void {
    const p = clampPace(this.d.spec, ms);
    if (p !== this.prefs.pace_ms) {
      this.prefs.pace_ms = p;
      this.rebuild();
    }
    if (fromWearer) this.send({ type: 'pref.changed', prefs: { pace_ms: p } });
    this.emit();
  }

  setAdvance(mode: Advance, fromWearer: boolean): void {
    this.prefs.advance = mode;
    if (fromWearer) this.send({ type: 'pref.changed', prefs: { advance: mode } });
    if (mode === 'auto' && this.waitingTap && !this.cur) {
      this.waitingTap = false;
      this.resume();
    }
    this.emit();
  }

  setLate(mode: Late, fromWearer: boolean): void {
    this.prefs.late = mode;
    if (fromWearer) this.send({ type: 'pref.changed', prefs: { late: mode } });
    this.emit();
  }

  setHistory(on: boolean, fromWearer: boolean): void {
    this.prefs.history = on;
    if (!on) this.historyList = [];
    if (fromWearer) this.send({ type: 'pref.changed', prefs: { history: on } });
    this.emit();
  }

  control(action: ControlAction): void {
    this.send({ type: 'control', action });
    const cur = this.cur;
    switch (action) {
      case 'stop':
        if (cur) {
          this.clearWait(cur);
          this.d.player.stop();
          cur.stopped = true;
        } else if (this.announcing) {
          this.d.player.stop();
          this.announcing = null;
        }
        break;
      case 'replay':
        if (cur) {
          cur.entry.cued = false; // a replay plays the cue again
          this.jumpTo(cur, 0);
        } else if (this.lastPlayed) {
          this.begin(this.lastPlayed, true);
        }
        break;
      case 'replay_word':
        if (cur) {
          const w = wordAt(cur);
          if (w !== null) this.jumpTo(cur, firstCellOf(cur.segs, w) ?? cur.idx);
        }
        break;
      case 'skip':
        if (cur && cur.segs[cur.idx]?.phase !== 'close') {
          const w = wordAt(cur);
          if (w !== null) this.jumpTo(cur, firstCellOf(cur.segs, w + 1) ?? closeOf(cur.segs));
        }
        break;
      case 'advance':
        if (this.waitingTap && !cur) {
          this.waitingTap = false;
          this.resume();
        } else if (cur) {
          // DECISION: advancing past an unfinished utterance drops it with a nack,
          // so the relay never waits out a handoff window on the wearer's choice.
          this.abandonCurrent();
          if (!cur.failed && !cur.local) this.nack(cur.entry.utt.id, 'cancelled_by_wearer');
          this.removeFromQueue(cur.entry);
          this.persist();
          this.waitingTap = false;
          this.resume();
        }
        break;
    }
    this.emit();
  }

  /** `visibilitychange`: a hidden page stops, refuses what it was playing, and resumes what it still holds when visible. */
  onVisibility(hidden: boolean): void {
    if (hidden) {
      this.pendingCues = [];
      this.stepAfterCue = false;
      if (this.announcing) {
        this.d.player.stop();
        this.announcing = null;
      }
      const cur = this.cur;
      if (cur) {
        this.abandonCurrent();
        if (!cur.local && !cur.failed) this.nack(cur.entry.utt.id, 'hidden');
        this.removeFromQueue(cur.entry);
        this.persist();
      }
    } else {
      this.resume();
    }
    this.emit();
  }

  // --- playback ---------------------------------------------------------------

  private begin(entry: HeldEntry, local: boolean): void {
    this.waitingTap = false;
    if (!local) {
      const exp = entry.utt.expires ? Date.parse(entry.utt.expires) : NaN;
      if (Number.isFinite(exp) && exp < this.wall() && this.prefs.late !== 'play') {
        this.nack(entry.utt.id, 'expired');
        this.removeFromQueue(entry);
        this.persist();
        this.afterTurn();
        return;
      }
    }
    this.cur = {
      entry,
      segs: this.buildSegs(entry),
      idx: 0,
      cursor: this.d.now(),
      started_ms: null,
      stopped: false,
      failed: false,
      local,
      workingStartedAt: null,
      lastWorkingAt: null,
      workingReported: false,
      waitTimer: null,
    };
    this.emit();
    this.step();
  }

  private buildSegs(entry: HeldEntry): Segment[] {
    const body = entry.body;
    const utt: Utterance =
      body && 'words' in body ? { ...entry.utt, words: body.words, body_pending: false } : entry.utt;
    return segments(utt, this.d.spec, this.prefs.pace_ms, this.d.profile);
  }

  /** At a segment boundary: announce waiting cues, then play the next segment. */
  private step(): void {
    const cur = this.cur;
    if (!cur || cur.stopped) return;
    if (this.announcing) {
      this.stepAfterCue = true;
      return;
    }
    if (this.pendingCues.length) {
      this.stepAfterCue = true;
      this.drainCues();
      return;
    }
    const seg = cur.segs[cur.idx];
    if (!seg) {
      this.finish(cur);
      return;
    }
    if (seg.phase === 'cue' && cur.entry.cued) {
      // DECISION: announced once already (between another utterance's cells); not repeated at its turn
      cur.idx += 1;
      this.step();
      return;
    }
    if (seg.phase === 'working') {
      this.working(cur, seg);
      return;
    }
    this.report(cur, seg);
    this.playSegment(cur, seg, () => {
      cur.idx += 1;
      this.step();
    });
  }

  private report(cur: Current, seg: Segment): void {
    if (cur.failed || cur.local) return;
    const id = cur.entry.utt.id;
    if (seg.phase === 'cue') {
      cur.entry.cued = true;
      this.send({ type: 'progress', id, phase: 'cue' });
    } else if (seg.phase === 'cell' && seg.word_index !== null && seg.letter_index === 0) {
      this.send({ type: 'progress', id, phase: 'word', word_index: seg.word_index });
    } else if (seg.phase === 'close') {
      this.send({ type: 'progress', id, phase: 'close' });
    }
  }

  private playSegment(cur: Current, seg: Segment, done: () => void): void {
    const startAt = Math.max(cur.cursor, this.d.now());
    if (cur.started_ms === null) cur.started_ms = startAt;
    this.emit();
    this.d.player.play(seg.beats, {
      startAt,
      total_ms: seg.length_ms + seg.gap_after_ms,
      onDone: (endAt) => {
        if (this.cur !== cur) return;
        cur.cursor = endAt;
        done();
      },
    });
  }

  private working(cur: Current, seg: Segment): void {
    if (cur.entry.body) {
      this.applyBody(cur);
      return;
    }
    const now = this.d.now();
    if (cur.workingStartedAt === null) cur.workingStartedAt = Math.max(cur.cursor, now);
    const timeoutAt = cur.workingStartedAt + (this.d.bodyTimeoutMs ?? DEFAULT_BODY_TIMEOUT_MS);
    if (now >= timeoutAt) {
      this.fail(cur, 'body_timeout');
      return;
    }
    const every = this.d.spec.working_every_ms;
    const due = cur.lastWorkingAt === null ? Math.max(cur.cursor, now) : cur.lastWorkingAt + every;
    const wakeAt = Math.min(due, timeoutAt);
    if (wakeAt > now + 1) {
      // silence until the next repeat (or the timeout); a body arriving meanwhile cuts the wait
      cur.waitTimer = this.d.setTimeout(() => {
        cur.waitTimer = null;
        this.step();
      }, wakeAt - now);
      this.emit();
      return;
    }
    cur.lastWorkingAt = due >= now - 1 ? due : now;
    cur.cursor = cur.lastWorkingAt;
    if (!cur.workingReported && !cur.local) {
      cur.workingReported = true;
      this.send({ type: 'progress', id: cur.entry.utt.id, phase: 'working' });
    }
    this.playSegment(cur, seg, () => this.step()); // idx stays on `working`; the next step re-decides
  }

  private applyBody(cur: Current): void {
    const body = cur.entry.body;
    if (!body) return;
    if ('error' in body) {
      this.fail(cur, body.error);
      return;
    }
    cur.segs = this.buildSegs(cur.entry);
    const first = cur.segs.findIndex((s) => s.phase === 'cell');
    cur.idx = first >= 0 ? first : closeOf(cur.segs);
    this.step();
  }

  /** The body never came, or came as an error: tell the relay once, then the error pattern and the close for the wearer. */
  private fail(cur: Current, reason: Reason): void {
    if (!cur.failed && !cur.local) this.nack(cur.entry.utt.id, reason);
    cur.failed = true;
    cur.segs = [...cur.segs.slice(0, cur.idx), ...errorSegments(this.d.spec)];
    this.step();
  }

  private finish(cur: Current): void {
    const entry = cur.entry;
    this.clearWait(cur);
    this.cur = null;
    if (!cur.failed && !cur.local) {
      this.send({
        type: 'played',
        id: entry.utt.id,
        started_ms: Math.max(0, Math.round(cur.started_ms ?? cur.cursor)),
        closed_ms: Math.max(0, Math.round(cur.cursor)),
      });
      this.lastAcked = entry.utt.id;
      this.lastPlayed = entry;
      if (this.prefs.history) {
        this.historyList.push({ id: entry.utt.id, kind: entry.utt.kind, label: entry.utt.from.label ?? null, words: wordsOf(entry), at: this.wall() });
        while (this.historyList.length > HISTORY_CAP) this.historyList.shift();
      }
    }
    this.removeFromQueue(entry);
    this.persist();
    this.afterTurn();
    this.emit();
  }

  /** After a close (or a drop): the next utterance starts by itself or waits for the wearer. */
  private afterTurn(): void {
    if (this.queue.length === 0 || this.d.isHidden()) return;
    if (this.prefs.advance === 'auto') this.resume();
    else this.waitingTap = true;
  }

  private drainCues(): void {
    if (this.announcing) return;
    const entry = this.pendingCues.shift();
    if (!entry) return;
    if (this.d.isHidden()) return;
    this.announcing = entry;
    entry.cued = true;
    this.send({ type: 'progress', id: entry.utt.id, phase: 'cue' });
    const seg = cueSegment(this.d.spec, entry.utt.kind);
    const cur = this.cur;
    const now = this.d.now();
    const startAt = cur && !cur.stopped && cur.waitTimer === null ? Math.max(cur.cursor, now) : now;
    this.emit();
    this.d.player.play(seg.beats, {
      startAt,
      total_ms: seg.length_ms + seg.gap_after_ms,
      onDone: (endAt) => {
        if (this.announcing !== entry) return;
        this.announcing = null;
        if (this.cur === cur && cur && !cur.stopped && cur.waitTimer === null) cur.cursor = endAt;
        if (this.pendingCues.length) {
          this.drainCues();
          return;
        }
        if (this.stepAfterCue) {
          this.stepAfterCue = false;
          this.step();
        }
        this.emit();
      },
    });
  }

  private jumpTo(cur: Current, idx: number): void {
    this.clearWait(cur);
    this.d.player.stop();
    cur.idx = Math.max(0, Math.min(idx, cur.segs.length));
    cur.cursor = this.d.now();
    cur.stopped = false;
    this.step();
  }

  private rebuild(): void {
    const cur = this.cur;
    if (!cur || cur.failed) return;
    const segs = this.buildSegs(cur.entry);
    // the structure only changes when the body arrives, which applyBody handles
    if (segs.length === cur.segs.length) cur.segs = segs;
  }

  private abandonCurrent(): void {
    const cur = this.cur;
    if (!cur) return;
    this.clearWait(cur);
    this.d.player.stop();
    this.cur = null;
    this.stepAfterCue = false;
  }

  private clearWait(cur: Current): void {
    if (cur.waitTimer !== null) {
      this.d.clearTimeout(cur.waitTimer);
      cur.waitTimer = null;
    }
  }

  private removeFromQueue(entry: HeldEntry): void {
    const i = this.queue.indexOf(entry);
    if (i >= 0) this.queue.splice(i, 1);
    this.pendingCues = this.pendingCues.filter((e) => e !== entry);
  }

  private persist(): void {
    const snap = {
      entries: this.queue.map((e) => ({ utt: e.utt, body: e.body, cued: e.cued, received_at: e.received_at })),
      last_acked: this.lastAcked,
    };
    this.d.store.save(snap).catch((err: unknown) => this.log(`queue not persisted: ${String(err)}`));
  }

  private nack(id: string, reason: Reason): void {
    this.send({ type: 'nack', id, reason });
  }

  private send(frame: UpFrame): void {
    this.d.send(frame);
  }

  private log(line: string): void {
    this.d.log?.(line);
  }

  private wall(): number {
    return this.d.wallClock ? this.d.wallClock() : Date.now();
  }

  private emit(): void {
    this.d.onChange?.(this.view());
  }
}

function wordsOf(entry: HeldEntry): string[] {
  const body = entry.body;
  return body && 'words' in body ? body.words : entry.utt.words;
}

/** The word the cursor is in, or the last one passed; null before any word. */
function wordAt(cur: Current): number | null {
  for (let i = Math.min(cur.idx, cur.segs.length - 1); i >= 0; i--) {
    const s = cur.segs[i];
    if (s && s.phase === 'cell' && s.word_index !== null) return s.word_index;
  }
  return null;
}

function firstCellOf(segs: Segment[], word: number): number | null {
  const i = segs.findIndex((s) => s.phase === 'cell' && s.word_index === word && s.letter_index === 0);
  return i >= 0 ? i : null;
}

function closeOf(segs: Segment[]): number {
  const i = segs.findIndex((s) => s.phase === 'close');
  return i >= 0 ? i : segs.length;
}
