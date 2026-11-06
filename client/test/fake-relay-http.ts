// A fake relay with the HTTP the headless driver needs (`GET /spec`,
// `POST /devices/enroll`) and a WebSocket at `/ws` that records every frame
// per connection and lets a test answer. No relay logic: the test is the relay.
import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { WebSocketServer } from 'ws';
import type { WebSocket as ServerSocket } from 'ws';
import type { DownFrame, UpFrame, Utterance } from '../src/wire.ts';
import { rawSpec } from './helpers.ts';

export const WAIT_MS = 8000;

export function withTimeout<T>(p: Promise<T>, what: string, ms = WAIT_MS): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`timed out waiting for ${what}`)), ms);
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

export interface Conn {
  ws: ServerSocket;
  frames: UpFrame[];
  closed: boolean;
}

export class FakeRelayHttp {
  readonly server: Server;
  readonly wss: WebSocketServer;
  readonly port: number;
  readonly conns: Conn[] = [];
  readonly enrolls: { code: string; profile: string; name: string }[] = [];
  /** the device key POST /devices/enroll hands out for `enrollCode` */
  readonly key = 'k'.repeat(32);
  readonly enrollCode = 'ABC123';
  private waiters: (() => void)[] = [];
  private readonly spec: Record<string, unknown>;

  private constructor(server: Server, wss: WebSocketServer, port: number, spec: Record<string, unknown>) {
    this.server = server;
    this.wss = wss;
    this.port = port;
    this.spec = spec;
    wss.on('connection', (ws) => {
      const conn: Conn = { ws, frames: [], closed: false };
      this.conns.push(conn);
      ws.on('message', (data) => {
        conn.frames.push(JSON.parse(data.toString()) as UpFrame);
        this.wake();
      });
      ws.on('close', () => {
        conn.closed = true;
        this.wake();
      });
      this.wake();
    });
  }

  static async start(spec: Record<string, unknown> = rawSpec()): Promise<FakeRelayHttp> {
    const holder: { relay: FakeRelayHttp | null } = { relay: null };
    const server = createServer((req, res) => holder.relay?.http(req, res));
    const wss = new WebSocketServer({ server, path: '/ws' });
    await withTimeout(new Promise<void>((r) => server.listen(0, '127.0.0.1', () => r())), 'relay listening');
    const port = (server.address() as AddressInfo).port;
    holder.relay = new FakeRelayHttp(server, wss, port, spec);
    return holder.relay;
  }

  get url(): string {
    return `ws://127.0.0.1:${this.port}`;
  }

  private http(req: IncomingMessage, res: ServerResponse): void {
    const url = new URL(req.url ?? '/', `http://${req.headers.host}`);
    if (req.method === 'GET' && url.pathname === '/spec') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(this.spec));
      return;
    }
    if (req.method === 'POST' && url.pathname === '/devices/enroll') {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        const b = JSON.parse(body) as { code: string; profile: string; name: string };
        this.enrolls.push(b);
        if (b.code !== this.enrollCode) {
          res.writeHead(401, { 'content-type': 'application/json' });
          res.end(JSON.stringify({ reason: 'unauthorized', message: 'unknown or expired enrollment code' }));
          return;
        }
        res.writeHead(201, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ device: 'd_cli', device_key: this.key }));
      });
      return;
    }
    res.writeHead(404, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ reason: 'not_found', message: 'no such route' }));
  }

  private wake(): void {
    const ws = this.waiters;
    this.waiters = [];
    for (const w of ws) w();
  }

  until(pred: () => boolean, what: string, ms = WAIT_MS): Promise<void> {
    if (pred()) return Promise.resolve();
    return withTimeout(
      new Promise<void>((resolve) => {
        const check = (): void => {
          if (pred()) resolve();
          else this.waiters.push(check);
        };
        this.waiters.push(check);
      }),
      `${what} (connections: ${this.conns.map((c) => c.frames.map((f) => f.type).join(',')).join(' | ')})`,
      ms,
    );
  }

  /** The n-th connection (0-based) once it exists and has sent its hello. */
  async connection(n: number): Promise<Conn> {
    await this.until(() => (this.conns[n]?.frames.length ?? 0) >= 1, `connection ${n} with hello`);
    return this.conns[n]!;
  }

  frame(conn: Conn, pred: (f: UpFrame) => boolean, what: string): Promise<UpFrame> {
    return this.until(() => conn.frames.some(pred), what).then(() => conn.frames.find(pred)!);
  }

  send(conn: Conn, frame: DownFrame): void {
    conn.ws.send(JSON.stringify(frame));
  }

  ack(conn: Conn, resend: Utterance[] = [], pace_ms = 420): void {
    this.send(conn, { type: 'hello.ack', wearer: 'w_1', device: 'd_cli', spec_version: Number(this.spec.version), prefs: { pace_ms, advance: 'auto' }, resend });
  }

  async close(): Promise<void> {
    for (const c of this.conns) c.ws.terminate();
    await new Promise<void>((r) => this.wss.close(() => r()));
    await new Promise<void>((r) => this.server.close(() => r()));
  }
}
