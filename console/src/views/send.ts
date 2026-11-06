import type { Kind, SubmitUtterance, UtteranceView } from "../generated/wire.ts";
import { KIND_VALUES } from "../generated/wire.ts";
import { clear, errorSlot, field, focusInert, h, uid } from "../dom.ts";
import { formatSeconds, joinWords } from "../format.ts";
import { normalise } from "../normalise.ts";
import type { AppContext, View } from "../router.ts";
import { watch } from "../watch.ts";
import { dl, errorText, isBusy, isInputProblem, setBusy } from "./common.ts";

export function sendView(ctx: AppContext): View {
  const countId = uid("send-count");
  const count = h("p", { id: countId, class: "count" }, "0 letters.");

  const textarea = h("textarea", { rows: "4", maxlength: "500", autocomplete: "off" });
  const text = field(textarea, {
    label: "Message",
    hint: "Letters a to z. Digits are spelled as words, punctuation is dropped. Length is a time budget, not a letter cap.",
    describedBy: [countId],
    required: true,
  });

  const kindSelect = h("select", null, ...KIND_VALUES.map((k) => h("option", { value: k, selected: k === "message" ? true : undefined }, k)));
  const kind = field(kindSelect, { label: "Kind", hint: "Selects the arrival cue the wearer feels first." });

  const labelInput = h("input", { type: "text", maxlength: "40", autocomplete: "off" });
  const label = field(labelInput, { label: "Label", hint: "Optional. Who or what this is from, up to 40 characters. Not played." });

  const lossyId = uid("lossy");
  const lossy = h("input", { type: "checkbox", id: lossyId });
  const lossyRow = h(
    "div",
    { class: "choice" },
    lossy,
    h("label", { for: lossyId }, "Allow lossy spelling: strip accents and drop characters that have no cell"),
  );

  const submit = h("button", { type: "submit" }, "Send");
  const form = h("form", { novalidate: true, "aria-labelledby": "send-title" });
  const formError = errorSlot(form);
  form.append(text.root, count, kind.root, label.root, lossyRow, h("div", { class: "actions" }, submit), formError.el);

  const resultTitle = uid("send-result");
  const resultBody = h("div");
  const result = h("section", { class: "result", hidden: true, tabindex: "-1", "aria-labelledby": resultTitle }, h("h2", { id: resultTitle }, "Sent"), resultBody);

  const updateCount = (): void => {
    const n = normalise(textarea.value, lossy.checked);
    if (!n.ok) {
      count.textContent = `${n.detail}.`;
      return;
    }
    const letters = `${n.letters} ${n.letters === 1 ? "letter" : "letters"}`;
    const words = n.words.length ? ` in ${n.words.length} ${n.words.length === 1 ? "word" : "words"}` : "";
    const respelled = n.lossy.length ? ` ${n.lossy.length} ${n.lossy.length === 1 ? "character" : "characters"} respelled.` : "";
    count.textContent = `${letters}${words}.${respelled}`;
  };
  textarea.addEventListener("input", updateCount);
  lossy.addEventListener("change", updateCount);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    text.setError(null);
    formError.set(null);
    const value = textarea.value.trim();
    if (!value) {
      text.setError("Type a message first.");
      ctx.announce("Error: type a message first.");
      textarea.focus();
      return;
    }
    const body: SubmitUtterance = { text: value, kind: kindSelect.value as Kind, allow_lossy: lossy.checked };
    if (labelInput.value.trim()) body.label = labelInput.value.trim();

    setBusy(submit, true);
    try {
      const view = await ctx.api.submitUtterance(body);
      showResult(view);
      watch(view.id, view.state);
      textarea.value = "";
      updateCount();
      ctx.announce(`Sent: ${joinWords(view.words)}. ${formatSeconds(view.duration_ms)} of ${formatSeconds(view.budget_ms)}. ${view.state}.`);
      focusInert(result);
    } catch (err) {
      result.hidden = true;
      const message = errorText(err);
      formError.set(message);
      if (isInputProblem(err)) {
        text.setError(message);
        textarea.focus();
      }
      ctx.announce(`Error: ${message}`);
    } finally {
      setBusy(submit, false);
    }
  });

  function showResult(view: UtteranceView): void {
    clear(resultBody);
    const lossyFlag = (view as { lossy?: boolean }).lossy === true;
    resultBody.append(
      dl([
        ["Words", h("span", { class: "words" }, joinWords(view.words))],
        ["Time", `${formatSeconds(view.duration_ms)} of the ${formatSeconds(view.budget_ms)} budget`],
        ["State", view.state],
        ["Kind", view.kind],
        ["Source", view.source],
        ...(lossyFlag ? ([["Spelling", "Lossy: some characters were respelled or dropped"]] as [string, string][]) : []),
        ["Id", h("span", { class: "secret" }, view.id)],
      ]),
      h("p", null, h("a", { href: "#/utterances" }, "Follow it in Utterances")),
    );
    result.hidden = false;
  }

  const element = h(
    "section",
    null,
    h("h1", { id: "send-title" }, "Send"),
    h("p", { class: "lede" }, "The relay normalises the text, measures it against the wearer's time budget and answers with the exact words that will be felt."),
    form,
    result,
  );
  return { element };
}
