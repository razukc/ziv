import type { Kind, ScheduleBody, ScheduleView } from "../generated/wire.ts";
import { KIND_VALUES } from "../generated/wire.ts";
import { clear, errorSlot, field, focusInert, h, uid } from "../dom.ts";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "../format.ts";
import type { AppContext, View } from "../router.ts";
import { errorText, isBusy, isInputProblem, pageError, setBusy } from "./common.ts";

export function scheduleView(ctx: AppContext): View {
  // --- the form -------------------------------------------------------------
  const fireInput = h("input", { type: "datetime-local", step: "60", value: toLocalInputValue(new Date(Date.now() + 60 * 60 * 1000)) });
  const fire = field(fireInput, { label: "When", hint: "Local time. The entry fires at this moment and is admitted like any message.", required: true });

  const kindSelect = h("select", null, ...KIND_VALUES.map((k) => h("option", { value: k, selected: k === "reminder" ? true : undefined }, k)));
  const kind = field(kindSelect, { label: "Kind" });

  const textArea = h("textarea", { rows: "3", maxlength: "500" });
  const text = field(textArea, { label: "Text", hint: "Played as written. Fill exactly one of Text and Intent." });

  const intentInput = h("input", { type: "text", maxlength: "200", autocomplete: "off" });
  const intent = field(intentInput, { label: "Intent", hint: "Composed by the agent when it fires, within the time budget." });

  const minutesInput = h("input", { type: "number", min: "1", max: "1440", step: "1", value: "60", inputmode: "numeric" });
  const minutes = field(minutesInput, { label: "Expires after, in minutes", hint: "1 to 1440. A reminder that misses this window is dropped or played late, per the wearer's preference." });

  const submit = h("button", { type: "submit" }, "Add to schedule");
  const form = h("form", { novalidate: true, "aria-labelledby": "schedule-form-title" });
  const formError = errorSlot(form);
  form.append(fire.root, kind.root, text.root, intent.root, minutes.root, h("div", { class: "actions" }, submit), formError.el);

  // --- the list -------------------------------------------------------------
  const error = pageError();
  const tbody = h("tbody");
  const table = h(
    "table",
    null,
    h("caption", null, "Scheduled entries, soonest first"),
    h(
      "thead",
      null,
      h("tr", null, h("th", { scope: "col" }, "When"), h("th", { scope: "col" }, "Kind"), h("th", { scope: "col" }, "Plays"), h("th", { scope: "col" }, "Action")),
    ),
    tbody,
  );
  const wrap = h("div", { class: "table-wrap", hidden: true }, table);
  const empty = h("p", null, "Nothing scheduled.");
  const listTitleId = uid("schedule-list");
  const listHeading = h("h2", { id: listTitleId }, "Entries");

  function render(list: ScheduleView[]): void {
    clear(tbody);
    for (const entry of list) tbody.append(row(entry));
    wrap.hidden = list.length === 0;
    empty.hidden = list.length > 0;
  }

  function row(entry: ScheduleView): HTMLTableRowElement {
    const when = formatDateTime(entry.fire_at);
    const plays = `${entry.label ?? "(no label)"}${entry.composed ? ", composed when it fires" : ", as written"}`;
    const del = h("button", { type: "button", class: "secondary", "aria-label": `Delete: ${entry.label ?? "entry"} at ${when}` }, "Delete");
    const tr = h("tr", { "data-id": String(entry.id) }, h("th", { scope: "row" }, when), h("td", null, entry.kind), h("td", null, plays), h("td", null, del));
    del.addEventListener("click", async () => {
      if (isBusy(del)) return;
      setBusy(del, true);
      error.set(null);
      try {
        await ctx.api.deleteSchedule(entry.id);
        const next = (tr.nextElementSibling ?? tr.previousElementSibling)?.querySelector("button");
        tr.remove();
        const left = tbody.children.length;
        wrap.hidden = left === 0;
        empty.hidden = left > 0;
        ctx.announce(`Deleted: ${entry.label ?? "entry"} at ${when}. ${left} left.`);
        if (next) next.focus();
        else focusInert(listHeading);
      } catch (err) {
        setBusy(del, false);
        error.set(`Could not delete the entry at ${when}. ${errorText(err)}`);
        ctx.announce(`Error: could not delete. ${errorText(err)}`);
      }
    });
    return tr;
  }

  async function load(manual: boolean): Promise<ScheduleView[] | null> {
    try {
      const list = await ctx.api.listSchedule();
      render(list);
      error.set(null);
      if (manual) ctx.announce(`Schedule refreshed. ${list.length} entries.`);
      return list;
    } catch (err) {
      error.set(errorText(err));
      if (manual) ctx.announce(`Error: ${errorText(err)}`);
      return null;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    for (const f of [fire, text, intent, minutes]) f.setError(null);
    formError.set(null);

    const fireAt = fromLocalInputValue(fireInput.value);
    const textValue = textArea.value.trim();
    const intentValue = intentInput.value.trim();
    const mins = Number(minutesInput.value);
    let firstBad: HTMLElement | null = null;
    if (!fireAt) {
      fire.setError("Enter a date and time.");
      firstBad = firstBad ?? fireInput;
    }
    if (Boolean(textValue) === Boolean(intentValue)) {
      text.setError("Fill exactly one of Text and Intent.");
      firstBad = firstBad ?? textArea;
    }
    if (!Number.isInteger(mins) || mins < 1 || mins > 1440) {
      minutes.setError("Enter whole minutes from 1 to 1440.");
      firstBad = firstBad ?? minutesInput;
    }
    if (firstBad) {
      ctx.announce("Error: the form has a problem. Fix the marked field.");
      firstBad.focus();
      return;
    }

    const body: ScheduleBody = { fire_at: fireAt as string, kind: kindSelect.value as Kind, expires_after_s: mins * 60 };
    if (textValue) body.text = textValue;
    else body.intent = intentValue;

    setBusy(submit, true);
    try {
      const created = await ctx.api.addSchedule(body);
      textArea.value = "";
      intentInput.value = "";
      await load(false);
      ctx.announce(`Added: ${created.label ?? "entry"} at ${formatDateTime(created.fire_at)}.`);
      const newRow = tbody.querySelector<HTMLTableRowElement>(`tr[data-id="${created.id}"]`);
      if (newRow) focusInert(newRow.firstElementChild as HTMLElement);
    } catch (err) {
      const message = errorText(err);
      formError.set(message);
      if (isInputProblem(err)) {
        (textValue ? text : intent).setError(message);
        (textValue ? textArea : intentInput).focus();
      }
      ctx.announce(`Error: ${message}`);
    } finally {
      setBusy(submit, false);
    }
  });

  const element = h(
    "section",
    null,
    h("h1", null, "Schedule"),
    h("p", { class: "lede" }, "Entries fire through the same admission as a message. The schedule refuses new rows at its cap; it never evicts the soonest."),
    h("section", { "aria-labelledby": "schedule-form-title" }, h("h2", { id: "schedule-form-title" }, "New entry"), form),
    h("section", { "aria-labelledby": listTitleId }, listHeading, error.el, empty, wrap),
  );
  return { element, ready: load(false).then(() => undefined) };
}

