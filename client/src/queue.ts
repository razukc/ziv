/**
 * The device's held utterances, persisted so a reload resumes with `held` ids
 * and `last_acked` in its hello. IndexedDB when the page has it, memory
 * otherwise; the snapshot is one record, written whole, so a crash mid-write
 * leaves the previous snapshot intact.
 */
import type { Reason, Utterance } from './wire.ts';

export type BodyState = { words: string[]; source?: string } | { error: Reason };

export interface HeldEntry {
  utt: Utterance;
  body: BodyState | null;
  /** the arrival cue has been played (announced between another utterance's cells) */
  cued: boolean;
  /** wall clock, ms since the epoch */
  received_at: number;
}

export interface QueueSnapshot {
  entries: HeldEntry[];
  last_acked: string | null;
}

export interface QueueStore {
  readonly kind: 'indexeddb' | 'memory';
  load(): Promise<QueueSnapshot>;
  save(snap: QueueSnapshot): Promise<void>;
}

const EMPTY: QueueSnapshot = { entries: [], last_acked: null };

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function checkSnapshot(v: unknown): QueueSnapshot {
  if (!v || typeof v !== 'object') return clone(EMPTY);
  const o = v as Record<string, unknown>;
  const entries = Array.isArray(o.entries) ? (o.entries as HeldEntry[]).filter((e) => e && typeof e === 'object' && e.utt && typeof e.utt.id === 'string') : [];
  return { entries, last_acked: typeof o.last_acked === 'string' ? o.last_acked : null };
}

export class MemoryQueueStore implements QueueStore {
  readonly kind = 'memory' as const;
  private snap: QueueSnapshot = clone(EMPTY);

  async load(): Promise<QueueSnapshot> {
    return clone(this.snap);
  }

  async save(snap: QueueSnapshot): Promise<void> {
    this.snap = clone(snap);
  }
}

const DB_NAME = 'ziv-device';
const STORE = 'state';
const KEY = 'queue';

function request<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error ?? new Error('indexeddb request failed'));
  });
}

function openDb(factory: IDBFactory, name: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = factory.open(name, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('indexeddb open failed'));
    req.onblocked = () => reject(new Error('indexeddb open blocked'));
  });
}

export class IndexedDbQueueStore implements QueueStore {
  readonly kind = 'indexeddb' as const;
  private readonly db: IDBDatabase;

  constructor(db: IDBDatabase) {
    this.db = db;
  }

  async load(): Promise<QueueSnapshot> {
    const tx = this.db.transaction(STORE, 'readonly');
    const v = await request(tx.objectStore(STORE).get(KEY));
    return checkSnapshot(v);
  }

  async save(snap: QueueSnapshot): Promise<void> {
    const tx = this.db.transaction(STORE, 'readwrite');
    await request(tx.objectStore(STORE).put(clone(snap), KEY));
  }
}

/** IndexedDB when available and openable; memory otherwise (the caller logs which). */
export async function openQueueStore(factory: IDBFactory | undefined, name: string = DB_NAME): Promise<QueueStore> {
  if (!factory) return new MemoryQueueStore();
  try {
    return new IndexedDbQueueStore(await openDb(factory, name));
  } catch {
    return new MemoryQueueStore();
  }
}
