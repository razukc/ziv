// Browser entry: the real environment behind the app.
import { mountApp } from './app.ts';
import { openQueueStore } from './queue.ts';

function safeStorage(): Storage | null {
  try {
    const s = window.localStorage;
    s.getItem('ziv.probe');
    return s;
  } catch {
    return null;
  }
}

const nav = navigator;
const vibrate = typeof nav.vibrate === 'function' ? (ms: number): void => void nav.vibrate(ms) : null;

mountApp(document, {
  fetch: (input, init) => fetch(input, init),
  WebSocket,
  storage: safeStorage(),
  now: () => performance.now(),
  setTimeout: (fn, ms) => window.setTimeout(fn, ms),
  clearTimeout: (h) => window.clearTimeout(h as number),
  vibrate,
  openStore: () => openQueueStore(globalThis.indexedDB),
  isHidden: () => document.hidden,
  onVisibility: (cb) => document.addEventListener('visibilitychange', () => cb(document.hidden)),
  defaultRelayUrl: location.origin,
});
