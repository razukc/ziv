// Shared bits for views: error wording, sections with headings, busy
// buttons that keep focus, a copy control, and a page-level error slot.

import { ApiError, describeReason } from "../api.ts";
import { h, uid } from "../dom.ts";
import type { AppContext } from "../router.ts";

/** Front-loaded wording for any failure: "Reason. Detail." */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) return `${describeReason(err.reason)}. ${err.detail}`;
  if (err instanceof Error) return `Unexpected. ${err.message}`;
  return `Unexpected. ${String(err)}`;
}

export function isInputProblem(err: unknown): boolean {
  return err instanceof ApiError && (err.reason === "unencodable" || err.reason === "over_budget" || err.reason === "bad_request");
}

export function section(title: string, ...children: (Node | string | null | false | undefined)[]): HTMLElement {
  const id = uid("sec");
  return h("section", { "aria-labelledby": id }, h("h2", { id }, title), ...children);
}

/** A page-level error paragraph (for loads and list actions, outside any form). */
export function pageError(): { el: HTMLParagraphElement; set(message: string | null): void } {
  const el = h("p", { class: "form-error", id: uid("page-error") });
  return {
    el,
    set(message) {
      el.textContent = message ? `Error: ${message}` : "";
    },
  };
}

/**
 * Mark a button busy without `disabled`, which would drop keyboard focus to
 * the body in the middle of a submit. Click handlers check isBusy().
 */
export function setBusy(button: HTMLButtonElement, busy: boolean): void {
  if (busy) {
    button.setAttribute("aria-disabled", "true");
    button.dataset["busy"] = "1";
  } else {
    button.removeAttribute("aria-disabled");
    delete button.dataset["busy"];
  }
}
export function isBusy(button: HTMLButtonElement): boolean {
  return button.dataset["busy"] === "1";
}

export function copyButton(ctx: AppContext, what: string, getText: () => string): HTMLButtonElement {
  const button = h("button", { type: "button", class: "secondary", "aria-label": `Copy ${what}` }, "Copy");
  button.addEventListener("click", async () => {
    const text = getText();
    try {
      if (!navigator.clipboard) throw new Error("no clipboard access");
      await navigator.clipboard.writeText(text);
      ctx.announce(`Copied ${what}.`);
    } catch {
      ctx.announce(`Copy failed. Select the ${what} text and copy it yourself.`);
    }
  });
  return button;
}

export function readonlyValue(id: string, labelText: string, value: string): { root: HTMLDivElement; input: HTMLInputElement } {
  const input = h("input", { id, type: "text", readonly: true, class: "secret", value, spellcheck: "false" });
  const root = h("div", { class: "field" }, h("label", { for: id }, labelText), input);
  return { root, input };
}

export function dl(rows: ReadonlyArray<[string, Node | string]>): HTMLDListElement {
  const list = h("dl");
  for (const [term, value] of rows) list.append(h("dt", null, term), h("dd", null, value));
  return list;
}

export function yesNo(value: boolean): string {
  return value ? "Yes" : "No";
}
