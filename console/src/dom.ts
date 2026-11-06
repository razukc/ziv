// Small DOM helpers. No framework: elements are built with h(), labelled
// fields with field(), and every id comes from uid() so label/for and
// aria-describedby pairs are always unique.

export type Child = Node | string | number | null | undefined | false;

type Handlers = { [event: string]: EventListener };
export type Attrs = {
  [name: string]: string | number | boolean | Handlers | null | undefined;
} & { on?: Handlers };

let counter = 0;
export function uid(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (name === "on" && typeof value === "object") {
        for (const [event, handler] of Object.entries(value)) el.addEventListener(event, handler);
      } else if (name === "class") {
        el.className = String(value);
      } else if (value === true) {
        el.setAttribute(name, "");
      } else {
        el.setAttribute(name, String(value));
      }
    }
  }
  append(el, ...children);
  return el;
}

export function append(parent: Node, ...children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    parent.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

/** Replace the text of an element only when it changed, so polling does not churn the accessibility tree. */
export function setText(el: Element, text: string): boolean {
  if (el.textContent === text) return false;
  el.textContent = text;
  return true;
}

export function visuallyHidden(text: string): HTMLSpanElement {
  return h("span", { class: "visually-hidden" }, text);
}

// --- labelled fields -------------------------------------------------------

export interface FieldOptions {
  /** Explicit, front-loaded label text. */
  label: string;
  hint?: string;
  /** Extra element ids to describe the control by (a live letter count, for example). */
  describedBy?: string[];
  required?: boolean;
}

export interface Field<T extends HTMLElement> {
  root: HTMLDivElement;
  control: T;
  id: string;
  errorId: string;
  /** Show an error under the field, mark it invalid and associate it. null clears. */
  setError(message: string | null): void;
}

/**
 * A labelled control: `<label for>`, an optional hint and an error slot, all
 * wired through aria-describedby. The control is created by the caller so the
 * field stays generic (input, select, textarea).
 */
export function field<T extends HTMLElement>(control: T, options: FieldOptions): Field<T> {
  const id = control.id || uid("f");
  control.id = id;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const label = h("label", { for: id }, options.label, options.required ? h("span", { "aria-hidden": "true" }, " *") : null);
  if (options.required) {
    control.setAttribute("required", "");
    control.setAttribute("aria-required", "true");
  }
  const hint = options.hint ? h("p", { id: hintId, class: "hint" }, options.hint) : null;
  const error = h("p", { id: errorId, class: "field-error" });
  const describers = [...(hint ? [hintId] : []), ...(options.describedBy ?? [])];
  const applyDescribedBy = (withError: boolean): void => {
    const ids = withError ? [errorId, ...describers] : describers;
    if (ids.length) control.setAttribute("aria-describedby", ids.join(" "));
    else control.removeAttribute("aria-describedby");
  };
  applyDescribedBy(false);
  const root = h("div", { class: "field" }, label, hint, control, error);
  return {
    root,
    control,
    id,
    errorId,
    setError(message) {
      if (message) {
        error.textContent = `Error: ${message}`;
        control.setAttribute("aria-invalid", "true");
        applyDescribedBy(true);
      } else {
        error.textContent = "";
        control.removeAttribute("aria-invalid");
        applyDescribedBy(false);
      }
    },
  };
}

/** A paragraph that holds a form-level error, associated with the form it sits in. */
export function errorSlot(form: HTMLFormElement): { el: HTMLParagraphElement; set(message: string | null): void } {
  const el = h("p", { id: uid("form-error"), class: "form-error" });
  return {
    el,
    set(message) {
      if (message) {
        el.textContent = `Error: ${message}`;
        form.setAttribute("aria-describedby", el.id);
      } else {
        el.textContent = "";
        form.removeAttribute("aria-describedby");
      }
    },
  };
}

/** Move keyboard focus to an element that is not normally focusable (a heading, a cell). */
export function focusInert(el: HTMLElement): void {
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: false });
}

export function isFocusWithin(el: Element): boolean {
  const active = document.activeElement;
  return Boolean(active && el.contains(active));
}
