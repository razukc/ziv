// A local preview of the relay's text normalisation (docs/ARCHITECTURE.md §2):
// lower-case, digits become words, punctuation is dropped, anything without
// a cell is refused unless lossy transliteration is allowed. The relay's
// answer is the truth; this exists so the Send view can show a live letter
// count without a round trip. The mock server imports the same function so
// the dev loop and the preview cannot disagree.

export const DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"] as const;
export const MAX_WORD_LETTERS = 32;
export const MAX_WORDS = 64;

export type Normalised =
  | { ok: true; words: string[]; letters: number; lossy: string[] }
  | { ok: false; reason: "unencodable" | "over_budget"; detail: string };

/** Characters joined silently rather than split: apostrophes inside a word. */
const JOINERS = new Set(["'", "’", "‘"]);

export function normalise(text: string, allowLossy = false): Normalised {
  const out: string[] = [];
  const lossy: string[] = [];
  let current = "";
  const flush = (): void => {
    if (current.length > 0) out.push(current);
    current = "";
  };

  for (const ch of text.normalize("NFC")) {
    if (ch >= "a" && ch <= "z") {
      current += ch;
    } else if (ch >= "A" && ch <= "Z") {
      current += ch.toLowerCase();
    } else if (ch >= "0" && ch <= "9") {
      flush();
      out.push(DIGIT_WORDS[ch.charCodeAt(0) - 48] as string);
    } else if (/\s/.test(ch)) {
      flush();
    } else if (JOINERS.has(ch)) {
      // dropped, no split: "don't" -> "dont"
    } else if (ch.charCodeAt(0) < 128) {
      // ASCII punctuation and symbols: dropped, splits the word
      flush();
    } else {
      // Outside the alphabet. Lossy: keep a base letter if the character has
      // one (e with acute -> e); otherwise the character is refused.
      const base = ch
        .normalize("NFKD")
        .replace(/[^A-Za-z]/g, "")
        .toLowerCase();
      if (!allowLossy) {
        return {
          ok: false,
          reason: "unencodable",
          detail: `"${ch}" has no braille cell; remove it or allow lossy spelling`,
        };
      }
      lossy.push(ch);
      if (base.length > 0) current += base;
      else flush();
    }
  }
  flush();

  for (const w of out) {
    if (w.length > MAX_WORD_LETTERS) {
      return { ok: false, reason: "unencodable", detail: `a word longer than ${MAX_WORD_LETTERS} letters cannot be sent` };
    }
  }
  if (out.length > MAX_WORDS) {
    return { ok: false, reason: "over_budget", detail: `more than ${MAX_WORDS} words` };
  }
  const letters = out.reduce((n, w) => n + w.length, 0);
  return { ok: true, words: out, letters, lossy };
}
