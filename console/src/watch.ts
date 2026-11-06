// Ids the user acted on in this tab (sent or cancelled). The Utterances view
// announces state changes for these and stays quiet about everything else.

import type { State } from "./generated/wire.ts";

const watched = new Map<string, State>();

export function watch(id: string, state: State): void {
  watched.set(id, state);
}

export function isWatched(id: string): boolean {
  return watched.has(id);
}

/** Records the new state; returns true when it differs from the last one seen. */
export function noteState(id: string, state: State): boolean {
  if (!watched.has(id)) return false;
  const before = watched.get(id);
  watched.set(id, state);
  return before !== state;
}
