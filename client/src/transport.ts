/**
 * The WebSocket to the relay. `hello` is always the first frame on a socket
 * (the device key travels in it, never in the URL); a reconnect backs off and
 * sends a fresh hello built from the device's current `last_acked` and `held`.
 * `ping` every 20 s is liveness only.
 */
import { describe, parseDownFrame, WireError } from './wire.ts';
import type { DownFrame, Hello, UpFrame } from './wire.ts';

export type TransportStatus = 'idle' | 'connecting' | 'open' | 'closed';

export interface TransportDeps {
  url: string;
  WebSocket: typeof WebSocket;
  makeHello: () => Hello;
  onFrame: (frame: DownFrame) => void;
  onStatus?: (status: TransportStatus, detail: string) => void;
  log?: (line: string) => void;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  pingEveryMs?: number;
  backoffInitialMs?: number;
  backoffMaxMs?: number;
}

export const PING_EVERY_MS = 20_000;
const OPEN = 1;

export class Transport {
  private readonly d: TransportDeps;
  private ws: WebSocket | null = null;
  private closedByUs = false;
  private backoff: number;
  private reconnectTimer: unknown = null;
  private pingTimer: unknown = null;
  status: TransportStatus = 'idle';

  constructor(deps: TransportDeps) {
    this.d = deps;
    this.backoff = deps.backoffInitialMs ?? 1000;
  }

  connect(): void {
    this.closedByUs = false;
    this.open();
  }

  close(): void {
    this.closedByUs = true;
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) ws.close();
    this.setStatus('closed', 'closed by the device');
  }

  /** Send a frame; false (and a log line) when the socket is not open. */
  send(frame: UpFrame): boolean {
    const ws = this.ws;
    if (!ws || ws.readyState !== OPEN) {
      this.d.log?.(`dropped (not connected): ${describe(frame)}`);
      return false;
    }
    ws.send(JSON.stringify(frame));
    this.d.log?.(`→ ${describe(frame)}`);
    return true;
  }

  private open(): void {
    this.setStatus('connecting', this.d.url);
    let ws: WebSocket;
    try {
      ws = new this.d.WebSocket(this.d.url);
    } catch (err) {
      this.d.log?.(`websocket: ${String(err)}`);
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.backoff = this.d.backoffInitialMs ?? 1000;
      // hello first, before anything else can be sent on this socket
      ws.send(JSON.stringify(this.d.makeHello()));
      this.d.log?.(`→ ${describe(this.d.makeHello())}`);
      this.setStatus('open', this.d.url);
      this.schedulePing();
    };
    ws.onmessage = (ev: MessageEvent) => {
      if (this.ws !== ws) return;
      const text = typeof ev.data === 'string' ? ev.data : '';
      let frame: DownFrame;
      try {
        frame = parseDownFrame(text);
      } catch (err) {
        this.d.log?.(`← unreadable frame: ${err instanceof WireError ? err.message : String(err)}`);
        return;
      }
      this.d.log?.(`← ${describe(frame)}`);
      this.d.onFrame(frame);
    };
    ws.onerror = () => {
      if (this.ws !== ws) return;
      this.d.log?.('websocket error');
    };
    ws.onclose = (ev: CloseEvent) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.clearTimers();
      this.setStatus('closed', `code ${ev.code}`);
      if (!this.closedByUs) this.scheduleReconnect();
    };
  }

  private schedulePing(): void {
    const every = this.d.pingEveryMs ?? PING_EVERY_MS;
    this.pingTimer = this.d.setTimeout(() => {
      this.pingTimer = null;
      if (this.ws && this.ws.readyState === OPEN) {
        this.send({ type: 'ping' });
        this.schedulePing();
      }
    }, every);
  }

  private scheduleReconnect(): void {
    if (this.closedByUs || this.reconnectTimer !== null) return;
    const wait = this.backoff;
    this.backoff = Math.min(this.d.backoffMaxMs ?? 30_000, this.backoff * 2);
    this.d.log?.(`reconnect in ${wait} ms`);
    this.reconnectTimer = this.d.setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closedByUs) this.open();
    }, wait);
  }

  private clearTimers(): void {
    if (this.pingTimer !== null) {
      this.d.clearTimeout(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.reconnectTimer !== null) {
      this.d.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setStatus(status: TransportStatus, detail: string): void {
    this.status = status;
    this.d.onStatus?.(status, detail);
  }
}
