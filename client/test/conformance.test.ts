import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { timeline } from '../src/sequencer.ts';
import { here, specV4, utt } from './helpers.ts';

const src = resolve(here, '..', 'src', 'conformance.ts');
const dist = resolve(here, '..', 'dist', 'conformance.js');

function run(entry: string, input: string, args: string[] = []): { out: string; err: string; status: number | null } {
  const r = spawnSync(process.execPath, [entry, ...args], { input, encoding: 'utf8' });
  return { out: r.stdout, err: r.stderr, status: r.status };
}

const u = utt({ kind: 'reminder', words: ['meds', 'nine'], prefix: { mark: 'ziv', tail: 'triple-pulse' } });

test('the conformance entry prints one valid JSONL beat per line, equal to the sequencer', () => {
  const spec = specV4();
  const r = run(src, JSON.stringify(u));
  assert.equal(r.status, 0, r.err);
  const lines = r.out.trimEnd().split('\n');
  const parsed = lines.map((l) => JSON.parse(l) as Record<string, unknown>);
  for (const b of parsed) {
    assert.deepEqual(Object.keys(b), ['t_ms', 'dot_mask', 'buzz_ms', 'label']);
    assert.ok(Number.isInteger(b.t_ms) && Number.isInteger(b.dot_mask) && Number.isInteger(b.buzz_ms));
    assert.equal(typeof b.label, 'string');
  }
  assert.deepEqual(parsed, timeline(u, spec, spec.cell_gap_default_ms, 'single_actuator'));
  assert.equal(parsed[0]!.label, 'prefix:z');
  assert.equal(parsed.at(-1)!.label, 'close');
});

test('--profile, --pace and --spec are honoured; a wrapped utterance is accepted', () => {
  const spec = specV4();
  const chord = run(src, JSON.stringify({ utterance: u, note: 'wrapper' }), ['--profile', 'six_actuator', '--pace', '300']);
  assert.equal(chord.status, 0, chord.err);
  const parsed = chord.out.trimEnd().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(parsed, timeline(u, spec, 300, 'six_actuator'));
  const fixture = run(src, JSON.stringify(u), ['--spec', resolve(here, 'fixtures', 'spec-v4.json')]);
  assert.equal(fixture.status, 1, 'the fixture lacks the letters of meds, so it refuses with a reason');
  assert.match(fixture.err, /no cell/);
});

test('bad input exits 1 with a reason on stderr and nothing on stdout', () => {
  const r = run(src, '{"id":"x"}');
  assert.equal(r.status, 1);
  assert.equal(r.out, '');
  assert.match(r.err, /conformance:/);
});

test('the built dist/conformance.js, when present, prints the same timeline as the source', { skip: !existsSync(dist) && 'run npm run build first' }, () => {
  const a = run(src, JSON.stringify(u));
  const b = run(dist, JSON.stringify(u));
  assert.equal(b.status, 0, b.err);
  assert.equal(b.out, a.out);
});
