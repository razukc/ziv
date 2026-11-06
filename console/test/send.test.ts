import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createMockServer } from "../mock/server.mjs";
import { installDom, input, submit, waitFor, type Dom } from "./_dom.ts";

type Mock = ReturnType<typeof createMockServer>;
let mock: Mock;
let origin: string;
let dom: Dom;
let views: typeof import("../src/views/send.ts");
let api: typeof import("../src/api.ts");
let live: typeof import("../src/announce.ts");

before(async () => {
  mock = createMockServer({ advanceMs: 0, budgetMs: 30000 });
  origin = await mock.listen(0);
  dom = installDom();
  views = await import("../src/views/send.ts");
  api = await import("../src/api.ts");
  live = await import("../src/announce.ts");
});
after(async () => {
  dom.window.close();
  await mock.close();
});

function context(token: string) {
  const client = new api.Api({ baseUrl: origin, token: () => token });
  const announced: string[] = [];
  const ctx = {
    api: client,
    announce: (t: string) => {
      announced.push(t);
      live.announce(t);
    },
    navigate: () => {},
    signedIn: () => true,
    spec: () => client.getSpec(),
  };
  return { ctx, announced };
}

test("Send: the letter count follows the text without a live region", async () => {
  const { ctx } = context("send-token");
  const view = views.sendView(ctx);
  dom.document.body.replaceChildren(view.element);
  const textarea = view.element.querySelector("textarea") as HTMLTextAreaElement;
  const count = dom.document.getElementById(textarea.getAttribute("aria-describedby")!.split(" ").find((id) => id.includes("send-count"))!)!;
  assert.equal(count.getAttribute("aria-live"), null);
  input(textarea, "Meds at 9");
  assert.equal(count.textContent, "10 letters in 3 words.");
  input(textarea, "mañana");
  assert.match(count.textContent ?? "", /no braille cell/);
  // a label is explicitly bound to the textarea
  const label = view.element.querySelector(`label[for="${textarea.id}"]`);
  assert.ok(label, "textarea has a <label for>");
});

test("Send: submitting renders the normalised words, the budget and the state, and announces once", async () => {
  mock.reset();
  const { ctx, announced } = context("send-token");
  const view = views.sendView(ctx);
  dom.document.body.replaceChildren(view.element);
  const form = view.element.querySelector("form") as HTMLFormElement;
  const textarea = form.querySelector("textarea") as HTMLTextAreaElement;
  input(textarea, "Tea at 4, don't be late");
  submit(form);
  const result = view.element.querySelector("section.result") as HTMLElement;
  await waitFor(() => !result.hidden, "the result section to show");
  await waitFor(() => live.liveText().length > 0, "the live region to fill");

  const text = result.textContent ?? "";
  assert.match(text, /tea at four dont be late/);
  assert.match(text, /of the 30 s budget/);
  assert.match(text, /pending/);
  assert.equal(dom.document.activeElement, result, "focus moves to the result");
  assert.equal(textarea.value, "", "the message box is cleared for the next one");
  assert.equal(announced.length, 1);
  assert.match(announced[0] ?? "", /^Sent: tea at four dont be late\./);
  assert.match(live.liveText(), /^Sent: tea at four/);
  assert.equal(form.querySelector(".form-error")?.textContent, "");
});

test("Send: an unencodable message renders the reason and detail into the error slot and the live region", async () => {
  mock.reset();
  const { ctx, announced } = context("send-token");
  const view = views.sendView(ctx);
  dom.document.body.replaceChildren(view.element);
  const form = view.element.querySelector("form") as HTMLFormElement;
  const textarea = form.querySelector("textarea") as HTMLTextAreaElement;
  input(textarea, "mañana");
  submit(form);
  const formError = form.querySelector(".form-error") as HTMLElement;
  await waitFor(() => (formError.textContent ?? "").length > 0, "the form error to render");
  await waitFor(() => live.liveText().length > 0, "the live region to fill");

  assert.match(formError.textContent ?? "", /^Error: Cannot be spelled in braille cells\. .*no braille cell/);
  assert.equal(form.getAttribute("aria-describedby"), formError.id, "form is described by its error");
  assert.equal(textarea.getAttribute("aria-invalid"), "true");
  const described = textarea.getAttribute("aria-describedby") ?? "";
  assert.ok(described.split(" ").includes(`${textarea.id}-error`), "textarea is described by its error");
  assert.equal(dom.document.activeElement, textarea, "focus returns to the field with the problem");
  assert.equal(announced.length, 1);
  assert.match(announced[0] ?? "", /^Error: Cannot be spelled in braille cells\./);
  assert.match(live.liveText(), /^Error: Cannot be spelled/);
  const region = dom.document.getElementById("live-status")!;
  assert.equal(region.getAttribute("aria-live"), "polite");
  assert.equal(region.getAttribute("role"), "status");
});

test("Send: over budget and unauthorized errors are shown with their reasons", async () => {
  mock.reset();
  const { ctx } = context("send-token");
  const view = views.sendView(ctx);
  dom.document.body.replaceChildren(view.element);
  const form = view.element.querySelector("form") as HTMLFormElement;
  const textarea = form.querySelector("textarea") as HTMLTextAreaElement;
  input(textarea, "abcdefghij ".repeat(40));
  submit(form);
  const err1 = form.querySelector(".form-error") as HTMLElement;
  await waitFor(() => (err1.textContent ?? "").length > 0, "the over-budget error");
  assert.match(err1.textContent ?? "", /^Error: Too long for the time budget\. .*budget is 30000 ms/);

  const ro = context("read-token");
  const view2 = views.sendView(ro.ctx);
  dom.document.body.replaceChildren(view2.element);
  const form2 = view2.element.querySelector("form") as HTMLFormElement;
  input(form2.querySelector("textarea") as HTMLTextAreaElement, "hello");
  submit(form2);
  const err2 = form2.querySelector(".form-error") as HTMLElement;
  await waitFor(() => (err2.textContent ?? "").length > 0, "the unauthorized error");
  assert.match(err2.textContent ?? "", /^Error: Not allowed with this token\. this token lacks the send scope/);
});
