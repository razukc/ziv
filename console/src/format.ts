// Formatting for people: local times, seconds not milliseconds, and words
// joined with spaces exactly as the relay echoed them.

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString(undefined, { timeStyle: "medium" });
}

export function formatSeconds(ms: number): string {
  const s = ms / 1000;
  return `${s >= 10 ? s.toFixed(0) : s.toFixed(1)} s`;
}

export function joinWords(words: readonly string[]): string {
  return words.length ? words.join(" ") : "(no words yet)";
}

/** Letters spaced out so a screen reader spells a code instead of guessing a word. */
export function spelled(code: string): string {
  return [...code].join(" ");
}

/** A value for <input type="datetime-local"> in local time, minute precision. */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The ISO instant for a datetime-local value, or null when it does not parse. */
export function fromLocalInputValue(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
