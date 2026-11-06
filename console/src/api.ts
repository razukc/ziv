// The relay's sender HTTP API, as the console speaks it (docs/ARCHITECTURE.md §6).
//
// Bodies are the generated types in ./generated/wire.ts; URLs, the bearer
// header and error mapping live here and nowhere else. Every non-2xx response
// becomes an ApiError that names a Reason, so a view can show the reason and
// the relay's detail instead of swallowing it.

import type {
  DeviceView,
  Health,
  Prefs,
  Reason,
  ScheduleBody,
  ScheduleView,
  State,
  SubmitUtterance,
  UtteranceView,
} from "./generated/wire.ts";
import { REASON_VALUES, STATE_VALUES } from "./generated/wire.ts";

/** A Reason from the wire, or one of two the console adds for its own failures. */
export type ErrorReason = Reason | "network" | "unexpected";

export class ApiError extends Error {
  readonly status: number;
  readonly reason: ErrorReason;
  readonly detail: string;
  /** Any other fields the relay put beside reason and detail (budget_ms, cap ...). */
  readonly extra: Readonly<Record<string, unknown>>;

  constructor(status: number, reason: ErrorReason, detail: string, extra: Record<string, unknown> = {}) {
    super(`${reason}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.reason = reason;
    this.detail = detail;
    this.extra = extra;
  }
}

export function isReason(value: unknown): value is Reason {
  return typeof value === "string" && (REASON_VALUES as readonly string[]).includes(value);
}

export function isState(value: unknown): value is State {
  return typeof value === "string" && (STATE_VALUES as readonly string[]).includes(value);
}

/** The status-code fallback when a body carries no usable reason. */
export function reasonForStatus(status: number): ErrorReason {
  switch (status) {
    case 401:
    case 403:
      return "unauthorized";
    case 413:
      return "over_budget";
    case 429:
      return "queue_full";
    case 400:
    case 404:
    case 409:
    case 422:
      return "bad_request";
    default:
      return "unexpected";
  }
}

export interface EnrollCode {
  code: string;
  expires: string;
}

export type SenderScope = "send" | "read";

export interface NewSender {
  label: string;
  scopes: SenderScope[];
}

/**
 * POST /senders answer. The architecture note names `sender`; ziv/wire.py's
 * SenderView names `id` and adds label, scopes and created. Both are accepted.
 */
export interface SenderCreated {
  token: string;
  sender?: string;
  id?: string;
  label?: string;
  scopes?: string[];
  created?: string;
}

/** The timing spec as served by GET /spec. The console reads the pace envelope only. */
export interface TimingSpec {
  version: number;
  constants: Record<string, number>;
  [key: string]: unknown;
}

export interface PaceEnvelope {
  min: number;
  max: number;
  default: number;
  step: number;
}

export function paceEnvelope(spec: TimingSpec): PaceEnvelope {
  const c = spec.constants;
  const min = c["cell_gap_min_ms"];
  const max = c["cell_gap_max_ms"];
  const dflt = c["cell_gap_default_ms"];
  if (typeof min !== "number" || typeof max !== "number" || typeof dflt !== "number" || min > max) {
    throw new ApiError(0, "unexpected", "the spec has no usable pace envelope (cell_gap_min_ms, cell_gap_max_ms, cell_gap_default_ms)");
  }
  const ui = spec["ui"];
  const step =
    ui && typeof ui === "object" && typeof (ui as Record<string, unknown>)["cell_gap_step_ms"] === "number"
      ? ((ui as Record<string, unknown>)["cell_gap_step_ms"] as number)
      : 10;
  return { min, max, default: dflt, step };
}

export interface ApiOptions {
  /** "" means the page's own origin. No trailing slash. */
  baseUrl?: string;
  /** Returns the bearer token, or null when signed out. */
  token?: () => string | null;
  fetch?: typeof fetch;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | undefined>;
  /** false for the public routes (health). */
  auth?: boolean;
}

export class Api {
  readonly baseUrl: string;
  private readonly tokenSource: () => string | null;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/+$/, "");
    this.tokenSource = options.token ?? (() => null);
    this.fetchImpl = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
  }

  url(path: string, query?: Record<string, string | undefined>): string {
    let url = this.baseUrl + path;
    if (query) {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== "") params.set(k, v);
      const qs = params.toString();
      if (qs) url += `?${qs}`;
    }
    return url;
  }

  hasToken(): boolean {
    return Boolean(this.tokenSource());
  }

  // --- utterances ---------------------------------------------------------

  submitUtterance(body: SubmitUtterance): Promise<UtteranceView> {
    return this.request<UtteranceView>("/utterances", { method: "POST", body });
  }

  listUtterances(state?: State): Promise<UtteranceView[]> {
    return this.request<UtteranceView[]>("/utterances", { query: { state } });
  }

  getUtterance(id: string): Promise<UtteranceView> {
    return this.request<UtteranceView>(`/utterances/${encodeURIComponent(id)}`);
  }

  /** Cancel. The relay answers with the view in its new state, or 204. */
  cancelUtterance(id: string): Promise<UtteranceView | undefined> {
    return this.request<UtteranceView | undefined>(`/utterances/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  // --- schedule -----------------------------------------------------------

  listSchedule(): Promise<ScheduleView[]> {
    return this.request<ScheduleView[]>("/schedule");
  }

  addSchedule(body: ScheduleBody): Promise<ScheduleView> {
    return this.request<ScheduleView>("/schedule", { method: "POST", body });
  }

  deleteSchedule(id: number): Promise<void> {
    return this.request<void>(`/schedule/${encodeURIComponent(String(id))}`, { method: "DELETE" });
  }

  // --- prefs --------------------------------------------------------------

  getPrefs(): Promise<Prefs> {
    return this.request<Prefs>("/prefs");
  }

  /** The relay clamps pace into the spec envelope and returns what it stored. */
  putPrefs(body: Prefs): Promise<Prefs> {
    return this.request<Prefs>("/prefs", { method: "PUT", body });
  }

  // --- devices and senders (admin) ------------------------------------------

  listDevices(): Promise<DeviceView[]> {
    return this.request<DeviceView[]>("/devices");
  }

  createEnrollCode(): Promise<EnrollCode> {
    return this.request<EnrollCode>("/devices/enroll-code", { method: "POST" });
  }

  createSender(body: NewSender): Promise<SenderCreated> {
    return this.request<SenderCreated>("/senders", { method: "POST", body });
  }

  // --- spec and health ----------------------------------------------------

  getSpec(): Promise<TimingSpec> {
    return this.request<TimingSpec>("/spec");
  }

  /** Public: no token is sent. */
  getHealth(): Promise<Health> {
    return this.request<Health>("/health", { auth: false });
  }

  // --- transport ----------------------------------------------------------

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = options.method ?? "GET";
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.auth !== false) {
      const token = this.tokenSource();
      if (!token) throw new ApiError(0, "unauthorized", "not signed in: paste a token first");
      headers["Authorization"] = `Bearer ${token}`;
    }
    const init: RequestInit = { method, headers, credentials: "omit", cache: "no-store" };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }

    let response: Response;
    try {
      response = await this.fetchImpl(this.url(path, options.query), init);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      throw new ApiError(0, "network", `could not reach the relay: ${detail}`);
    }

    const text = await response.text();
    let parsed: unknown = undefined;
    if (text.length > 0) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = undefined;
      }
    }

    if (!response.ok) throw errorFrom(response.status, response.statusText, parsed, text);
    if (response.status === 204 || text.length === 0) return undefined as T;
    if (parsed === undefined) {
      throw new ApiError(response.status, "unexpected", "the relay answered with something that is not JSON");
    }
    return parsed as T;
  }
}

function errorFrom(status: number, statusText: string, parsed: unknown, raw: string): ApiError {
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const { reason, detail, ...extra } = parsed as Record<string, unknown>;
    const r: ErrorReason = isReason(reason) ? reason : reasonForStatus(status);
    const d = typeof detail === "string" && detail.length > 0 ? detail : `HTTP ${status}${statusText ? ` ${statusText}` : ""}`;
    return new ApiError(status, r, d, extra);
  }
  const snippet = raw.length > 120 ? `${raw.slice(0, 120)}…` : raw;
  return new ApiError(status, reasonForStatus(status), snippet || `HTTP ${status}${statusText ? ` ${statusText}` : ""}`);
}

/** Plain words for a reason, front-loaded for a braille display. */
export function describeReason(reason: ErrorReason): string {
  switch (reason) {
    case "queue_full":
      return "Queue full";
    case "over_budget":
      return "Too long for the time budget";
    case "unencodable":
      return "Cannot be spelled in braille cells";
    case "expired":
      return "Expired";
    case "spec_mismatch":
      return "Device spec mismatch";
    case "body_timeout":
      return "Body did not arrive in time";
    case "hidden":
      return "Device hidden";
    case "muted":
      return "Device muted";
    case "device_gone":
      return "Device gone";
    case "failover":
      return "Moved to another device";
    case "compose_failed":
      return "Compose failed";
    case "cancelled_by_sender":
      return "Cancelled by sender";
    case "cancelled_by_wearer":
      return "Cancelled by wearer";
    case "unauthorized":
      return "Not allowed with this token";
    case "bad_request":
      return "Rejected";
    case "network":
      return "No connection to the relay";
    case "unexpected":
      return "Unexpected answer from the relay";
  }
}
