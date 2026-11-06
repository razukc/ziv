/**
 * Conformance entry: an utterance JSON on stdin, the timeline as JSONL on stdout,
 * one `{"t_ms","dot_mask","buzz_ms","label"}` per line at the spec's default
 * pace, so `conformance/run.py --player "node client/dist/conformance.js"` can
 * diff this renderer against the reference.
 *
 *   --spec <path>      the timing spec (default: docs/haptic-timing.json at the repo root)
 *   --profile <name>   six_actuator | single_actuator (default: single_actuator)
 *   --pace <ms>        cell gap (default: the spec's cell_gap_default_ms)
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { timeline } from './sequencer.ts';
import { resolveSpec } from './spec.ts';
import type { ProfileName } from './spec.ts';
import { checkUtterance } from './wire.ts';

interface Args {
  spec: string | null;
  profile: ProfileName;
  pace: number | null;
}

function parseArgs(argv: string[]): Args {
  const out: Args = { spec: null, profile: 'single_actuator', pace: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    const [flag, inline] = a.includes('=') ? (a.split(/=(.*)/s) as [string, string]) : [a, undefined];
    const value = (): string => {
      if (inline !== undefined) return inline;
      const v = argv[++i];
      if (v === undefined) throw new Error(`${flag} needs a value`);
      return v;
    };
    switch (flag) {
      case '--spec':
        out.spec = value();
        break;
      case '--profile': {
        const p = value();
        if (p !== 'six_actuator' && p !== 'single_actuator') throw new Error(`unknown profile ${p}`);
        out.profile = p;
        break;
      }
      case '--pace': {
        const n = Number(value());
        if (!Number.isInteger(n)) throw new Error('--pace needs an integer');
        out.pace = n;
        break;
      }
      default:
        process.stderr.write(`conformance: ignoring unknown argument ${a}\n`);
    }
  }
  return out;
}

export function main(argv: string[], stdin: string): string {
  const args = parseArgs(argv);
  const here = dirname(fileURLToPath(import.meta.url));
  const specPath = args.spec ?? resolve(here, '..', '..', 'docs', 'haptic-timing.json');
  const spec = resolveSpec(JSON.parse(readFileSync(specPath, 'utf8')));
  const input = JSON.parse(stdin) as unknown;
  const wrapped = input && typeof input === 'object' && 'utterance' in (input as object) ? (input as { utterance: unknown }).utterance : input;
  const utt = checkUtterance(wrapped);
  const pace = args.pace ?? spec.cell_gap_default_ms;
  let out = '';
  for (const b of timeline(utt, spec, pace, args.profile)) {
    out += JSON.stringify({ t_ms: b.t_ms, dot_mask: b.dot_mask, buzz_ms: b.buzz_ms, label: b.label }) + '\n';
  }
  return out;
}

try {
  process.stdout.write(main(process.argv.slice(2), readFileSync(0, 'utf8')));
} catch (err) {
  process.stderr.write(`conformance: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exitCode = 1;
}
