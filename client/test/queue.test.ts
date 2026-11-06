import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MemoryQueueStore, openQueueStore } from '../src/queue.ts';
import { utt } from './helpers.ts';

test('the memory store round-trips a snapshot by value', async () => {
  const s = new MemoryQueueStore();
  assert.deepEqual(await s.load(), { entries: [], last_acked: null });
  const u = utt({ words: ['hi'] });
  const snap = { entries: [{ utt: u, body: null, cued: false, received_at: 1 }], last_acked: 'x'.repeat(10) };
  await s.save(snap);
  snap.entries.length = 0; // the store keeps its own copy
  const back = await s.load();
  assert.equal(back.entries.length, 1);
  assert.equal(back.entries[0]!.utt.id, u.id);
  assert.equal(back.last_acked, 'x'.repeat(10));
});

test('without IndexedDB the store falls back to memory', async () => {
  const s = await openQueueStore(undefined);
  assert.equal(s.kind, 'memory');
});
