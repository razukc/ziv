import type { State, UtteranceView } from "../generated/wire.ts";
import { STATE_VALUES } from "../generated/wire.ts";
import { field, focusInert, h, isFocusWithin, setText, uid } from "../dom.ts";
import { formatDateTime, formatSeconds, formatTime, joinWords } from "../format.ts";
import type { AppContext, View } from "../router.ts";
import { noteState, watch } from "../watch.ts";
import { errorText, isBusy, pageError, setBusy } from "./common.ts";

export const POLL_MS = 4000;
const ACTIVE: ReadonlySet<State> = new Set<State>(["pending", "sent", "playing"]);

interface Row {
  tr: HTMLTableRowElement;
  words: HTMLTableCellElement;
  kind: HTMLTableCellElement;
  state: HTMLTableCellElement;
  time: HTMLTableCellElement;
  created: HTMLTableCellElement;
  action: HTMLTableCellElement;
  view: UtteranceView;
  /** A poll arrived while focus was inside; apply on the next one. */
  stale?: UtteranceView | null;
}

export function utterancesView(ctx: AppContext): View {
  const error = pageError();
  const status = h("p", { class: "status-line", id: uid("utt-status") }, "Loading…");

  const stateSelect = h(
    "select",
    null,
    h("option", { value: "" }, "All states"),
    ...STATE_VALUES.map((s) => h("option", { value: s }, s)),
  );
  const stateField = field(stateSelect, { label: "Show", hint: "Filter by outbox state. The list refreshes on its own while this tab is visible." });
  const refresh = h("button", { type: "button", class: "secondary" }, "Refresh now");

  const tbody = h("tbody");
  const table = h(
    "table",
    null,
    h("caption", null, "Utterances, newest first"),
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        h("th", { scope: "col" }, "Words"),
        h("th", { scope: "col" }, "Kind"),
        h("th", { scope: "col" }, "State"),
        h("th", { scope: "col" }, "Time"),
        h("th", { scope: "col" }, "Created"),
        h("th", { scope: "col" }, "Action"),
      ),
    ),
    tbody,
  );
  const wrap = h("div", { class: "table-wrap" }, table);
  const empty = h("p", { hidden: true }, "No utterances in this state.");

  const rows = new Map<string, Row>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let mounted = false;
  let loading = false;

  function stateText(view: UtteranceView): string {
    return view.reason && view.reason !== "cancelled_by_sender" ? `${view.state} (${view.reason.replaceAll("_", " ")})` : view.state;
  }
  function timeText(view: UtteranceView): string {
    return `${formatSeconds(view.duration_ms)} of ${formatSeconds(view.budget_ms)}`;
  }

  function makeRow(view: UtteranceView): Row {
    const words = h("th", { scope: "row", class: "words" }, joinWords(view.words));
    const row: Row = {
      tr: h("tr", { "data-id": view.id }),
      words: words as unknown as HTMLTableCellElement,
      kind: h("td", null, view.kind),
      state: h("td", { tabindex: "-1" }, stateText(view)),
      time: h("td", null, timeText(view)),
      created: h("td", null, formatDateTime(view.created)),
      action: h("td"),
      view,
    };
    row.tr.append(words, row.kind, row.state, row.time, row.created, row.action);
    renderAction(row);
    return row;
  }

  function renderAction(row: Row): void {
    const wantButton = ACTIVE.has(row.view.state);
    const existing = row.action.querySelector("button");
    if (wantButton && !existing) {
      const button = h("button", { type: "button", class: "secondary", "aria-label": `Cancel: ${joinWords(row.view.words)}` }, "Cancel");
      button.addEventListener("click", () => void cancel(row, button));
      row.action.append(button);
    } else if (!wantButton && existing) {
      existing.remove();
      row.action.textContent = "";
    }
    if (!wantButton && !row.action.textContent) row.action.textContent = "—";
    if (wantButton) {
      // keep only the button
      for (const n of [...row.action.childNodes]) if (n.nodeType === Node.TEXT_NODE) n.remove();
    }
  }

  function applyView(row: Row, view: UtteranceView): void {
    row.view = view;
    setText(row.kind, view.kind);
    setText(row.state, stateText(view));
    setText(row.time, timeText(view));
    renderAction(row);
  }

  async function cancel(row: Row, button: HTMLButtonElement): Promise<void> {
    if (isBusy(button)) return;
    setBusy(button, true);
    error.set(null);
    const words = joinWords(row.view.words);
    try {
      const updated = (await ctx.api.cancelUtterance(row.view.id)) ?? { ...row.view, state: "cancelled" as State, reason: "cancelled_by_sender" as const };
      watch(updated.id, updated.state);
      // Focus moves to the state cell before the button goes away.
      focusInert(row.state);
      applyView(row, updated);
      ctx.announce(`Cancelled: ${words}. Now ${updated.state}.`);
    } catch (err) {
      setBusy(button, false);
      error.set(`Could not cancel ${words}. ${errorText(err)}`);
      ctx.announce(`Error: could not cancel ${words}. ${errorText(err)}`);
    }
  }

  function reconcile(list: UtteranceView[]): void {
    const seen = new Set<string>();
    const tableFocused = isFocusWithin(table);
    let anchor: ChildNode | null = tbody.firstChild;
    for (const view of list) {
      seen.add(view.id);
      if (noteState(view.id, view.state)) ctx.announce(`${joinWords(view.words)} is now ${view.state}.`);
      let row = rows.get(view.id);
      if (!row) {
        row = makeRow(view);
        rows.set(view.id, row);
        tbody.insertBefore(row.tr, anchor);
        continue;
      }
      if (isFocusWithin(row.tr)) {
        row.stale = view;
      } else {
        applyView(row, row.stale && row.stale.updated > view.updated ? row.stale : view);
        row.stale = null;
        if (!tableFocused && row.tr !== anchor) tbody.insertBefore(row.tr, anchor);
      }
      if (row.tr === anchor) anchor = anchor.nextSibling;
      else if (!tableFocused) anchor = row.tr.nextSibling;
    }
    for (const [id, row] of rows) {
      if (seen.has(id)) continue;
      if (isFocusWithin(row.tr)) continue; // never pull the row out from under the user
      row.tr.remove();
      rows.delete(id);
    }
    const none = rows.size === 0;
    empty.hidden = !none;
    wrap.hidden = none;
  }

  async function load(manual: boolean): Promise<void> {
    if (loading) return;
    loading = true;
    if (manual) setBusy(refresh, true);
    try {
      const filter = stateSelect.value as State | "";
      const list = await ctx.api.listUtterances(filter || undefined);
      reconcile(list);
      error.set(null);
      setText(status, `Updated ${formatTime(new Date().toISOString())}. ${rows.size} shown. Refreshes every ${POLL_MS / 1000} seconds while this tab is visible.`);
      if (manual) ctx.announce(`Refreshed. ${rows.size} utterances shown.`);
    } catch (err) {
      error.set(errorText(err));
      if (manual) ctx.announce(`Error: ${errorText(err)}`);
    } finally {
      loading = false;
      if (manual) setBusy(refresh, false);
      schedule();
    }
  }

  function schedule(): void {
    if (timer) clearTimeout(timer);
    timer = null;
    if (!mounted || document.hidden) return;
    timer = setTimeout(() => void load(false), POLL_MS);
  }

  const onVisibility = (): void => {
    if (document.hidden) {
      if (timer) clearTimeout(timer);
      timer = null;
      setText(status, `Paused while this tab is hidden.`);
    } else {
      void load(false);
    }
  };

  stateSelect.addEventListener("change", () => {
    for (const row of rows.values()) row.tr.remove();
    rows.clear();
    void load(true);
  });
  refresh.addEventListener("click", () => void load(true));

  const element = h(
    "section",
    null,
    h("h1", null, "Utterances"),
    h("p", { class: "lede" }, "Everything admitted for the wearer, in its outbox state. Pending, sent and playing ones can be cancelled."),
    h("div", { class: "actions" }, stateField.root, refresh),
    status,
    error.el,
    empty,
    wrap,
  );

  const ready = load(false);
  return {
    element,
    ready,
    mount() {
      mounted = true;
      document.addEventListener("visibilitychange", onVisibility);
      schedule();
    },
    unmount() {
      mounted = false;
      document.removeEventListener("visibilitychange", onVisibility);
      if (timer) clearTimeout(timer);
      timer = null;
    },
  };
}
