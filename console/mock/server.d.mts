// Types for mock/server.mjs, for the tests' typecheck.

export interface MockOptions {
  spec?: unknown;
  budgetMs?: number;
  /** 0 disables the simulated pending -> sent -> playing -> played progression. */
  advanceMs?: number;
  cors?: boolean;
  staticDir?: string | null;
  adminToken?: string;
  sendToken?: string;
  readToken?: string;
  log?: (line: string) => void;
}

export interface MockServer {
  server: import("node:http").Server;
  state: {
    senders: Map<string, { sender: string; label: string; scopes: string[] }>;
    utterances: Map<string, Record<string, unknown>>;
    schedule: Record<string, unknown>[];
    prefs: { pace_ms: number; advance: string; late: string; history: boolean };
    devices: Record<string, unknown>[];
    counters: Record<string, number>;
    /** what the last POST /compose carried: the body, and the bring-your-own-key header or null */
    lastCompose: { body: Record<string, unknown>; key: string | null } | null;
  };
  reset(): void;
  /** Resolves with the origin, e.g. http://127.0.0.1:43210 */
  listen(port?: number, host?: string): Promise<string>;
  close(): Promise<void>;
}

export function createMockServer(options?: MockOptions): MockServer;
