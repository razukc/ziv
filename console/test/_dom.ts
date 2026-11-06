// jsdom bootstrap for DOM-level tests. Call installDom() before importing
// any module that touches `document`, then import views dynamically.

import { JSDOM, VirtualConsole } from "jsdom";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

export interface Dom {
  dom: JSDOM;
  window: JSDOM["window"];
  document: Document;
}

const GLOBALS = [
  "window",
  "document",
  "Node",
  "Element",
  "HTMLElement",
  "HTMLInputElement",
  "HTMLButtonElement",
  "HTMLFormElement",
  "HTMLTableRowElement",
  "Event",
  "CustomEvent",
  "KeyboardEvent",
  "MouseEvent",
  "SubmitEvent",
  "Storage",
  "getComputedStyle",
] as const;

export function installDom(): Dom {
  // Forward page console output, but drop jsdom's "Not implemented" noise
  // (axe probes canvas for colour work; there is no layout engine here).
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err: Error) => {
    if (!/Not implemented/.test(err.message)) console.error(err);
  });
  for (const level of ["log", "warn", "error", "info"] as const) virtualConsole.on(level, (...args: unknown[]) => console[level](...args));
  const dom = new JSDOM("<!doctype html><html lang='en'><head><title>test</title></head><body data-ziv-test='1'></body></html>", {
    url: "http://console.test/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole,
  });
  const w = dom.window as unknown as Record<string, unknown>;
  for (const name of GLOBALS) {
    if (name in w) Object.defineProperty(globalThis, name, { value: w[name], configurable: true, writable: true });
  }
  // navigator is a getter on Node's globalThis; replace it so clipboard checks see jsdom's.
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true, writable: true });
  return { dom, window: dom.window, document: dom.window.document };
}

/** Load axe-core into the jsdom window and run it on the body. */
export async function runAxe(dom: Dom): Promise<AxeViolation[]> {
  const require = createRequire(import.meta.url);
  const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
  dom.window.eval(axeSource);
  const axe = (dom.window as unknown as { axe: { run: (ctx: unknown, opts: unknown) => Promise<{ violations: AxeViolation[] }> } }).axe;
  const results = await axe.run(dom.document.body, {
    // Colour contrast needs a layout engine; jsdom has none, so it is marked
    // incomplete rather than failing. Everything else runs.
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations;
}

export interface AxeViolation {
  id: string;
  impact: "minor" | "moderate" | "serious" | "critical" | null;
  help: string;
  nodes: { html: string; target: string[]; failureSummary?: string }[];
}

export function serious(violations: AxeViolation[]): AxeViolation[] {
  return violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

export function describeViolations(violations: AxeViolation[]): string {
  return violations.map((v) => `${v.impact} ${v.id}: ${v.help}\n  ${v.nodes.map((n) => n.html).join("\n  ")}`).join("\n");
}

export function submit(form: HTMLFormElement): void {
  form.dispatchEvent(new (globalThis as unknown as { Event: typeof Event }).Event("submit", { bubbles: true, cancelable: true }));
}

export function input(el: HTMLElement, value: string): void {
  (el as HTMLInputElement).value = value;
  el.dispatchEvent(new (globalThis as unknown as { Event: typeof Event }).Event("input", { bubbles: true }));
}

export async function settle(ms = 80): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

/** Poll a condition instead of sleeping a fixed time; fails loudly after the timeout. */
export async function waitFor(check: () => boolean, what = "condition", timeoutMs = 5000): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (check()) return;
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error(`timed out after ${timeoutMs} ms waiting for ${what}`);
}
