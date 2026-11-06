/**
 * Compose-box normalisation, as an aid before the relay's own: letters are
 * lower-cased, digits are spelled out one by one, and anything else is refused
 * with the character named. The relay still normalises what it receives.
 */
import { MAX_WORDS, MAX_WORD_LETTERS } from './wire.ts';

const DIGITS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];

export type ComposeResult = { ok: true; words: string[] } | { ok: false; reason: string };

export function composeWords(text: string): ComposeResult {
  const words: string[] = [];
  for (const raw of text.trim().split(/\s+/)) {
    if (!raw) continue;
    let cur = '';
    for (const ch of raw) {
      if (ch >= 'a' && ch <= 'z') {
        cur += ch;
      } else if (ch >= 'A' && ch <= 'Z') {
        cur += ch.toLowerCase();
      } else if (ch >= '0' && ch <= '9') {
        if (cur) {
          words.push(cur);
          cur = '';
        }
        words.push(DIGITS[ch.charCodeAt(0) - 48]!);
      } else {
        return { ok: false, reason: `"${ch}" has no cell: use letters a to z and digits only` };
      }
    }
    if (cur) words.push(cur);
  }
  if (words.length === 0) return { ok: false, reason: 'type at least one word' };
  if (words.length > MAX_WORDS) return { ok: false, reason: `at most ${MAX_WORDS} words in one message` };
  const long = words.find((w) => w.length > MAX_WORD_LETTERS);
  if (long) return { ok: false, reason: `"${long}" is longer than ${MAX_WORD_LETTERS} letters` };
  return { ok: true, words };
}
