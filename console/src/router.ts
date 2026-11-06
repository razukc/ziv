// Hash routing: #/send, #/utterances ... A hash that is not a route (the skip
// link's #main) is left alone, so the browser can focus the target.

import type { Api } from "./api.ts";

export const ROUTES = ["signin", "send", "utterances", "schedule", "prefs", "devices", "senders", "health"] as const;
export type Route = (typeof ROUTES)[number];

export const ROUTE_TITLES: Record<Route, string> = {
  signin: "Sign in",
  send: "Send",
  utterances: "Utterances",
  schedule: "Schedule",
  prefs: "Preferences",
  devices: "Devices",
  senders: "Senders",
  health: "Health",
};

/** Routes that work without a token. */
export const PUBLIC_ROUTES: ReadonlySet<Route> = new Set<Route>(["signin", "health"]);

export function isRoute(value: string): value is Route {
  return (ROUTES as readonly string[]).includes(value);
}

export function routeFromHash(hash: string): Route | null {
  const m = /^#\/([a-z]+)\/?$/.exec(hash);
  if (!m) return null;
  const name = m[1] ?? "";
  return isRoute(name) ? name : null;
}

export function hashFor(route: Route): string {
  return `#/${route}`;
}

export interface View {
  element: HTMLElement;
  /** Resolves when the first load has rendered (tests wait on it). */
  ready?: Promise<void>;
  /** Start timers and listeners. Called after the element is in the document. */
  mount?(): void;
  /** Stop timers and listeners. */
  unmount?(): void;
}

export interface AppContext {
  api: Api;
  announce(text: string): void;
  navigate(route: Route): void;
  signedIn(): boolean;
  /** Pace envelope and spec version, fetched once per sign-in. */
  spec(): Promise<import("./api.ts").TimingSpec>;
}

export type ViewFactory = (ctx: AppContext) => View;
