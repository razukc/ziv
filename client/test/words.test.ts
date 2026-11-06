import assert from 'node:assert/strict';
import { test } from 'node:test';
import { composeWords } from '../src/words.ts';

test('letters lower-case, digits spelled out one by one, whitespace splits', () => {
  assert.deepEqual(composeWords('  Meds at 9 '), { ok: true, words: ['meds', 'at', 'nine'] });
  assert.deepEqual(composeWords('room 42'), { ok: true, words: ['room', 'four', 'two'] });
  assert.deepEqual(composeWords('a1b'), { ok: true, words: ['a', 'one', 'b'] });
});

test('anything without a cell is refused, naming the character', () => {
  const r = composeWords("don't");
  assert.equal(r.ok, false);
  if (!r.ok) assert.match(r.reason, /"'"/);
  assert.equal(composeWords('hi!').ok, false);
  assert.equal(composeWords('é').ok, false);
  assert.equal(composeWords('   ').ok, false);
});

test('wire limits are enforced before sending', () => {
  assert.equal(composeWords('a'.repeat(33)).ok, false);
  assert.equal(composeWords(Array(65).fill('a').join(' ')).ok, false);
  assert.equal(composeWords(Array(64).fill('a').join(' ')).ok, true);
});
