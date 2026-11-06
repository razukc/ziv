// The bearer token lives in sessionStorage only: it goes away with the tab
// and is never written to localStorage, a cookie or the URL.

const KEY = "ziv.console.token";
type Listener = (token: string | null) => void;
const listeners = new Set<Listener>();

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  try {
    return storage()?.getItem(KEY) ?? null;
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    storage()?.setItem(KEY, token);
  } catch {
    // Storage unavailable (private mode, disabled): the token is held for
    // this page load only, through the in-memory fallback below.
    memory = token;
  }
  emit();
}

export function forgetToken(): void {
  memory = null;
  try {
    storage()?.removeItem(KEY);
  } catch {
    // nothing to forget
  }
  emit();
}

let memory: string | null = null;
export function currentToken(): string | null {
  return getToken() ?? memory;
}

export function onSessionChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  const t = currentToken();
  for (const l of listeners) l(t);
}
