import type { ComposeBody, Kind, SubmitUtterance, UtteranceView } from "../generated/wire.ts";
import { KIND_VALUES } from "../generated/wire.ts";
import { clear, errorSlot, field, focusInert, h, uid } from "../dom.ts";
import { formatSeconds, joinWords } from "../format.ts";
import { normalise } from "../normalise.ts";
import type { AppContext, View } from "../router.ts";
import { watch } from "../watch.ts";
import { dl, errorText, isBusy, isInputProblem, setBusy } from "./common.ts";

export type SendMode = "type" | "agent";

/** Plain words for an utterance's `source`, so the wire never implies a model ran when it did not. */
export function describeSource(source: string): string {
  switch (source) {
    case "live":
      return "live: a model wrote the line";
    case "echo":
      return "echo: your words, played as typed (no model ran)";
    case "sender":
      return "sender: typed by you, normalised by the relay";
    default:
      return source;
  }
}

export function sendView(ctx: AppContext): View {
  // --- mode -----------------------------------------------------------------
  const modeName = uid("send-mode");
  const modeType = h("input", { type: "radio", name: modeName, value: "type", id: uid("mode"), checked: true });
  const modeAgent = h("input", { type: "radio", name: modeName, value: "agent", id: uid("mode") });
  const modeSet = h(
    "fieldset",
    null,
    h("legend", null, "Mode"),
    h("div", { class: "choice" }, modeType, h("label", { for: modeType.id }, "Type the words")),
    h("div", { class: "choice" }, modeAgent, h("label", { for: modeAgent.id }, "Ask the agent")),
  );
  const mode = (): SendMode => (modeAgent.checked ? "agent" : "type");

  // --- type the words -------------------------------------------------------
  const countId = uid("send-count");
  const count = h("p", { id: countId, class: "count" }, "0 letters.");

  const textarea = h("textarea", { rows: "4", maxlength: "500", autocomplete: "off" });
  const text = field(textarea, {
    label: "Message",
    hint: "Letters a to z. Digits are spelled as words, punctuation is dropped. Length is a time budget, not a letter cap.",
    describedBy: [countId],
    required: true,
  });

  const lossyId = uid("lossy");
  const lossy = h("input", { type: "checkbox", id: lossyId });
  const lossyRow = h(
    "div",
    { class: "choice" },
    lossy,
    h("label", { for: lossyId }, "Allow lossy spelling: strip accents and drop characters that have no cell"),
  );
  const typeFields = h("div", null, text.root, count, lossyRow);

  // --- ask the agent --------------------------------------------------------
  const intentInput = h("input", { type: "text", maxlength: "200", autocomplete: "off" });
  const intent = field(intentInput, {
    label: "Intent",
    hint: "What the wearer should learn, in your words. The agent compresses it into a short line that fits the time budget. The device cues at once and plays the working pattern until the line is ready. Without a model, the relay plays your words as typed and says so (source: echo).",
    required: true,
  });
  const keyInput = h("input", { type: "password", maxlength: "256", autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
  const key = field(keyInput, {
    label: "Use my own Token Factory key",
    hint: "Optional. Sent once, in a request header, for this compose only; the relay uses it for that call and keeps nothing. This field is cleared after every request. Leave it empty to use the relay's own model, or echo when it has none.",
  });
  const agentFields = h("div", { hidden: true }, intent.root, key.root);

  // --- shared ---------------------------------------------------------------
  const kindSelect = h("select", null, ...KIND_VALUES.map((k) => h("option", { value: k, selected: k === "message" ? true : undefined }, k)));
  const kind = field(kindSelect, { label: "Kind", hint: "Selects the arrival cue the wearer feels first." });

  const labelInput = h("input", { type: "text", maxlength: "40", autocomplete: "off" });
  const label = field(labelInput, { label: "Label", hint: "Optional. Who or what this is from, up to 40 characters. Not played." });

  const submit = h("button", { type: "submit" }, "Send");
  const form = h("form", { novalidate: true, "aria-labelledby": "send-title" });
  const formError = errorSlot(form);
  form.append(modeSet, typeFields, agentFields, kind.root, label.root, h("div", { class: "actions" }, submit), formError.el);

  const resultTitleId = uid("send-result");
  const resultTitle = h("h2", { id: resultTitleId }, "Sent");
  const resultBody = h("div");
  const result = h("section", { class: "result", hidden: true, tabindex: "-1", "aria-labelledby": resultTitleId }, resultTitle, resultBody);

  const applyMode = (): void => {
    const agent = mode() === "agent";
    typeFields.hidden = agent;
    agentFields.hidden = !agent;
    submit.textContent = agent ? "Ask the agent" : "Send";
    // a composed line is a reminder unless the sender says otherwise; typed words are a message
    const untouched = kindSelect.dataset["touched"] !== "1";
    if (untouched) kindSelect.value = agent ? "reminder" : "message";
    result.hidden = true;
    formError.set(null);
    text.setError(null);
    intent.setError(null);
  };
  modeType.addEventListener("change", applyMode);
  modeAgent.addEventListener("change", applyMode);
  kindSelect.addEventListener("change", () => {
    kindSelect.dataset["touched"] = "1";
  });

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
    intent.setError(null);
    formError.set(null);
    if (mode() === "agent") await askAgent();
    else await sendTyped();
  });

  async function sendTyped(): Promise<void> {
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
      showResult("Sent", view);
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
  }

  async function askAgent(): Promise<void> {
    const value = intentInput.value.trim();
    if (!value) {
      intent.setError("Say what the wearer should learn first.");
      ctx.announce("Error: say what the wearer should learn first.");
      intentInput.focus();
      return;
    }
    const body: ComposeBody = { intent: value, kind: kindSelect.value as Kind };
    if (labelInput.value.trim()) body.label = labelInput.value.trim();
    // the key travels in the header of this one request and nowhere else; the field is emptied either way
    const apiKey = keyInput.value.trim() || undefined;
    keyInput.value = "";

    setBusy(submit, true);
    try {
      const view = await ctx.api.compose(body, apiKey);
      watch(view.id, view.state);
      if (view.state === "failed") {
        showResult("Not composed", view);
        const message = `Compose failed. The agent could not produce a line that fits the budget; the wearer felt the error pattern. ${view.reason ? `Reason: ${view.reason.replaceAll("_", " ")}.` : ""}`;
        formError.set(message);
        ctx.announce(`Error: ${message}`);
        focusInert(result);
        return;
      }
      showResult("Composed", view);
      intentInput.value = "";
      ctx.announce(
        `Composed: ${joinWords(view.words)}. ${formatSeconds(view.duration_ms)} of ${formatSeconds(view.budget_ms)}. ${view.state}. Source ${view.source}.`,
      );
      focusInert(result);
    } catch (err) {
      result.hidden = true;
      const message = errorText(err);
      formError.set(message);
      if (isInputProblem(err)) {
        intent.setError(message);
        intentInput.focus();
      }
      ctx.announce(`Error: ${message}`);
    } finally {
      setBusy(submit, false);
    }
  }

  function showResult(title: string, view: UtteranceView): void {
    clear(resultBody);
    resultTitle.textContent = title;
    const lossyFlag = (view as { lossy?: boolean }).lossy === true;
    const stateText = view.reason ? `${view.state} (${view.reason.replaceAll("_", " ")})` : view.state;
    resultBody.append(
      dl([
        ["Words", h("span", { class: "words" }, joinWords(view.words))],
        ["Time", `${formatSeconds(view.duration_ms)} of the ${formatSeconds(view.budget_ms)} budget`],
        ["State", stateText],
        ["Kind", view.kind],
        ["Source", h("span", { class: "source", "data-source": view.source }, describeSource(view.source))],
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
    h(
      "p",
      { class: "lede" },
      "Type the words and the relay normalises them, measures them against the wearer's time budget and answers with the exact words that will be felt. Or ask the agent: it turns an intent into a short line, and the answer says whether a model wrote it.",
    ),
    form,
    result,
  );
  return { element };
}
