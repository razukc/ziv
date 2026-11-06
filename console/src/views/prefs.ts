import type { Advance, Late, Prefs } from "../generated/wire.ts";
import { paceEnvelope, type PaceEnvelope } from "../api.ts";
import { errorSlot, field, h, uid } from "../dom.ts";
import type { AppContext, View } from "../router.ts";
import { errorText, isBusy, pageError, setBusy } from "./common.ts";

export function prefsView(ctx: AppContext): View {
  const error = pageError();
  const paceInput = h("input", { type: "number", step: "10", inputmode: "numeric" });
  const pace = field(paceInput, { label: "Pace, in milliseconds", hint: "Loading the envelope from the spec…", required: true });

  const advanceName = uid("advance");
  const advanceAuto = h("input", { type: "radio", name: advanceName, value: "auto", id: uid("adv") });
  const advanceTap = h("input", { type: "radio", name: advanceName, value: "tap", id: uid("adv") });
  const advanceSet = h(
    "fieldset",
    null,
    h("legend", null, "Next message"),
    h("div", { class: "choice" }, advanceAuto, h("label", { for: advanceAuto.id }, "Automatic: the next message starts by itself after the close")),
    h("div", { class: "choice" }, advanceTap, h("label", { for: advanceTap.id }, "Tap: wait until the wearer releases it")),
  );

  const lateName = uid("late");
  const lateDrop = h("input", { type: "radio", name: lateName, value: "drop", id: uid("late") });
  const latePlay = h("input", { type: "radio", name: lateName, value: "play", id: uid("late") });
  const lateSet = h(
    "fieldset",
    null,
    h("legend", null, "Reminders that arrive after they expire"),
    h("div", { class: "choice" }, lateDrop, h("label", { for: lateDrop.id }, "Drop it and count it")),
    h("div", { class: "choice" }, latePlay, h("label", { for: latePlay.id }, "Play it with the late tail")),
  );

  const historyId = uid("history");
  const history = h("input", { type: "checkbox", id: historyId });
  const historyRow = h("div", { class: "choice" }, history, h("label", { for: historyId }, "Keep a message history on the phone. Off by default; on, it is stored encrypted and bounded."));

  const submit = h("button", { type: "submit" }, "Save preferences");
  const form = h("form", { novalidate: true, "aria-labelledby": "prefs-title" });
  const formError = errorSlot(form);
  form.append(pace.root, advanceSet, lateSet, historyRow, h("div", { class: "actions" }, submit), formError.el);

  let envelope: PaceEnvelope | null = null;

  function fill(prefs: Prefs): void {
    if (typeof prefs.pace_ms === "number") paceInput.value = String(prefs.pace_ms);
    advanceAuto.checked = prefs.advance !== "tap";
    advanceTap.checked = prefs.advance === "tap";
    lateDrop.checked = prefs.late !== "play";
    latePlay.checked = prefs.late === "play";
    history.checked = prefs.history === true;
  }

  async function load(): Promise<void> {
    try {
      const [spec, prefs] = await Promise.all([ctx.spec(), ctx.api.getPrefs()]);
      envelope = paceEnvelope(spec);
      paceInput.min = String(envelope.min);
      paceInput.max = String(envelope.max);
      paceInput.step = String(envelope.step);
      const hint = pace.root.querySelector(".hint");
      if (hint) hint.textContent = `Gap between cells, from ${envelope.min} to ${envelope.max} ms. Default ${envelope.default}. Lower is faster. The relay clamps into this range.`;
      if (paceInput.value === "") paceInput.value = String(envelope.default);
      fill(prefs);
      error.set(null);
    } catch (err) {
      error.set(errorText(err));
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    pace.setError(null);
    formError.set(null);
    const requested = Number(paceInput.value);
    if (!Number.isFinite(requested) || paceInput.value.trim() === "") {
      pace.setError("Enter a pace in milliseconds.");
      ctx.announce("Error: enter a pace in milliseconds.");
      paceInput.focus();
      return;
    }
    if (envelope && (requested < envelope.min || requested > envelope.max)) {
      pace.setError(`Pace must be from ${envelope.min} to ${envelope.max} ms.`);
      ctx.announce(`Error: pace must be from ${envelope.min} to ${envelope.max} milliseconds.`);
      paceInput.focus();
      return;
    }
    const body: Prefs = {
      pace_ms: Math.round(requested),
      advance: (advanceTap.checked ? "tap" : "auto") as Advance,
      late: (latePlay.checked ? "play" : "drop") as Late,
      history: history.checked,
    };
    setBusy(submit, true);
    try {
      const stored = await ctx.api.putPrefs(body);
      fill(stored);
      const clamped = typeof stored.pace_ms === "number" && stored.pace_ms !== body.pace_ms ? ` Pace clamped to ${stored.pace_ms} ms.` : "";
      ctx.announce(
        `Saved.${clamped} Pace ${stored.pace_ms ?? body.pace_ms} ms, next message ${stored.advance ?? body.advance}, late reminders ${stored.late ?? body.late}, history ${stored.history ? "on" : "off"}.`,
      );
    } catch (err) {
      formError.set(errorText(err));
      ctx.announce(`Error: ${errorText(err)}`);
    } finally {
      setBusy(submit, false);
    }
  });

  const element = h(
    "section",
    null,
    h("h1", { id: "prefs-title" }, "Preferences"),
    h("p", { class: "lede" }, "The wearer's settings, synchronised to the device through the relay. Pace is the gap between braille cells."),
    error.el,
    form,
  );
  return { element, ready: load() };
}
