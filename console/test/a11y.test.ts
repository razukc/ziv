// Accessibility smoke: every view rendered against the mock, checked with
// axe-core in jsdom. Zero violations at the serious and critical levels is
// the acceptance bar; anything lower is printed for the reviewer.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createMockServer } from "../mock/server.mjs";
import { describeViolations, installDom, input, runAxe, serious, settle, submit, waitFor, type Dom } from "./_dom.ts";

type Mock = ReturnType<typeof createMockServer>;
let mock: Mock;
let origin: string;
let dom: Dom;
let main: typeof import("../src/main.ts");
let api: typeof import("../src/api.ts");
let session: typeof import("../src/session.ts");
let shell: import("../src/main.ts").Shell;

before(async () => {
  mock = createMockServer({ advanceMs: 0 });
  origin = await mock.listen(0);
  dom = installDom();
  // main.ts reads __API_BASE__ once at import; point it at the mock first.
  (globalThis as unknown as { __API_BASE__: string }).__API_BASE__ = origin;
  main = await import("../src/main.ts");
  api = await import("../src/api.ts");
  session = await import("../src/session.ts");
  // seed some state so tables have rows
  const seed = new api.Api({ baseUrl: origin, token: () => "send-token" });
  await seed.submitUtterance({ text: "meds nine", kind: "reminder" });
  await seed.submitUtterance({ text: "call back" });
  await seed.addSchedule({ fire_at: new Date(Date.now() + 3_600_000).toISOString(), intent: "pills" });
});
after(async () => {
  shell?.stop();
  dom.window.close();
  await mock.close();
});

const ROUTES = ["signin", "send", "utterances", "schedule", "prefs", "devices", "senders", "health"] as const;

async function open(route: string): Promise<void> {
  dom.window.location.hash = `#/${route}`;
  await settle(20); // jsdom fires hashchange asynchronously
  if (shell.route() !== route) dom.window.dispatchEvent(new dom.window.Event("hashchange"));
  await waitFor(() => shell.route() === route, `route ${route}`);
  await shell.current()?.ready;
}

test("shell: landmarks, skip link, nav with aria-current, one h1 per view", async () => {
  session.setToken("admin-token");
  shell = main.start(dom.document.body);
  await shell.current()?.ready;
  assert.ok(dom.document.querySelector("header[role=banner]"));
  assert.ok(dom.document.querySelector("nav[aria-label=Console]"));
  assert.ok(dom.document.querySelector("main#main"));
  assert.equal(dom.document.querySelector("a.skip-link")?.getAttribute("href"), "#main");
  assert.equal(dom.document.querySelectorAll("[role=status][aria-live=polite]").length, 1);

  for (const route of ROUTES) {
    await open(route);
    const h1s = dom.document.querySelectorAll("h1");
    assert.equal(h1s.length, 1, `${route}: exactly one h1`);
    assert.equal(dom.document.activeElement, h1s[0], `${route}: focus moves to the heading`);
    const current = dom.document.querySelectorAll("nav a[aria-current=page]");
    assert.equal(current.length, 1, `${route}: one current nav link`);
    assert.equal(current[0]?.getAttribute("href"), `#/${route}`);
    assert.match(dom.document.title, /– Ziv console$/);
  }
});

test("every control has a label and every form field an explicit <label for>", async () => {
  for (const route of ROUTES) {
    await open(route);
    const controls = dom.document.querySelectorAll<HTMLElement>("main input, main select, main textarea");
    for (const c of controls) {
      const id = c.id;
      const label = id ? dom.document.querySelector(`label[for="${id}"]`) : null;
      assert.ok(label && (label.textContent ?? "").trim().length > 0, `${route}: <${c.tagName.toLowerCase()} id="${id}"> has a <label for>`);
    }
    for (const b of dom.document.querySelectorAll<HTMLButtonElement>("main button")) {
      const name = b.getAttribute("aria-label") ?? b.textContent ?? "";
      assert.ok(name.trim().length > 0, `${route}: button has a name`);
      assert.equal(b.getAttribute("onclick"), null, "no inline handlers");
    }
    for (const t of dom.document.querySelectorAll("main table")) {
      assert.ok(t.querySelector("caption"), `${route}: table has a caption`);
      assert.ok(t.querySelectorAll("th[scope=col]").length > 0, `${route}: table has column headers`);
    }
  }
});

test("axe: zero serious or critical violations on every view, including error and result states", async () => {
  const report: string[] = [];
  for (const route of ROUTES) {
    await open(route);
    const violations = await runAxe(dom);
    const bad = serious(violations);
    if (bad.length) report.push(`[${route}]\n${describeViolations(bad)}`);
    const minor = violations.filter((v) => !bad.includes(v));
    if (minor.length) console.log(`note (${route}, below serious): ${minor.map((v) => v.id).join(", ")}`);
  }

  // Send with an error shown, then with a result shown.
  await open("send");
  const form = dom.document.querySelector("main form") as HTMLFormElement;
  input(form.querySelector("textarea") as HTMLTextAreaElement, "mañana");
  submit(form);
  await waitFor(() => (form.querySelector(".form-error")?.textContent ?? "").length > 0, "send error");
  assert.match(form.querySelector(".form-error")?.textContent ?? "", /^Error:/);
  let bad = serious(await runAxe(dom));
  if (bad.length) report.push(`[send/error]\n${describeViolations(bad)}`);

  input(form.querySelector("textarea") as HTMLTextAreaElement, "all good");
  submit(form);
  await waitFor(() => !(dom.document.querySelector("main section.result") as HTMLElement).hidden, "send result");
  bad = serious(await runAxe(dom));
  if (bad.length) report.push(`[send/result]\n${describeViolations(bad)}`);

  // Devices with an enroll code displayed, Senders with a token displayed.
  await open("devices");
  (dom.document.querySelector("main section section button") as HTMLButtonElement).click();
  await waitFor(() => Boolean(dom.document.querySelector("main .code-display")), "enroll code");
  assert.match(dom.document.querySelector("main .code-display")?.textContent ?? "", /^[0-9A-Z]{6,12}$/);
  bad = serious(await runAxe(dom));
  if (bad.length) report.push(`[devices/code]\n${describeViolations(bad)}`);

  await open("senders");
  const sform = dom.document.querySelector("main form") as HTMLFormElement;
  input(sform.querySelector("input[type=text]") as HTMLInputElement, "mum");
  submit(sform);
  await waitFor(() => Boolean(dom.document.querySelector("main input.secret")), "sender token");
  assert.ok(dom.document.querySelector("main input.secret"), "token shown in a readonly field");
  bad = serious(await runAxe(dom));
  if (bad.length) report.push(`[senders/token]\n${describeViolations(bad)}`);

  assert.equal(report.length, 0, `axe violations:\n${report.join("\n\n")}`);
});

test("utterances: polling updates rows in place and never moves focus", async () => {
  await open("utterances");
  const table = dom.document.querySelector("main table") as HTMLTableElement;
  const firstCancel = table.querySelector("tbody button") as HTMLButtonElement;
  assert.ok(firstCancel, "a pending row has a Cancel button");
  firstCancel.focus();
  assert.equal(dom.document.activeElement, firstCancel);
  // a new utterance arrives behind the user's back
  await new api.Api({ baseUrl: origin, token: () => "send-token" }).submitUtterance({ text: "later" });
  const before = table.querySelector("tbody")!.children.length;
  (dom.document.querySelector("main .actions button") as HTMLButtonElement).click(); // Refresh now
  await waitFor(() => table.querySelector("tbody")!.children.length > before, "the new row");
  assert.equal(dom.document.activeElement, firstCancel, "focus stays on the control the user was on");
  // cancel: focus lands on the row's state cell, which now reads cancelled
  const row = firstCancel.closest("tr") as HTMLTableRowElement;
  const stateCell = row.children[2] as HTMLElement;
  firstCancel.click();
  await waitFor(() => /cancelled/.test(stateCell.textContent ?? ""), "the row to read cancelled");
  assert.equal(dom.document.activeElement, stateCell, "focus moved to the state cell before the button went away");
  assert.equal(row.querySelector("button"), null);
});
