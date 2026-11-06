import type { DeviceView } from "../generated/wire.ts";
import { clear, h, uid, focusInert } from "../dom.ts";
import { formatDateTime, spelled } from "../format.ts";
import type { AppContext, View } from "../router.ts";
import { copyButton, errorText, isBusy, pageError, readonlyValue, setBusy, yesNo } from "./common.ts";

const PROFILE_TEXT: Record<string, string> = {
  six_actuator: "six actuators (band)",
  single_actuator: "single actuator (phone)",
};

export function devicesView(ctx: AppContext): View {
  const error = pageError();
  const refresh = h("button", { type: "button", class: "secondary" }, "Refresh");
  const tbody = h("tbody");
  const table = h(
    "table",
    null,
    h("caption", null, "Enrolled devices"),
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        h("th", { scope: "col" }, "Name"),
        h("th", { scope: "col" }, "Profile"),
        h("th", { scope: "col" }, "Primary"),
        h("th", { scope: "col" }, "Connected"),
        h("th", { scope: "col" }, "Last seen"),
      ),
    ),
    tbody,
  );
  const wrap = h("div", { class: "table-wrap", hidden: true }, table);
  const empty = h("p", null, "No devices enrolled.");

  function render(list: DeviceView[]): void {
    clear(tbody);
    for (const d of list) {
      tbody.append(
        h(
          "tr",
          null,
          h("th", { scope: "row" }, d.name),
          h("td", null, PROFILE_TEXT[d.profile] ?? d.profile),
          h("td", null, yesNo(d.primary)),
          h("td", null, yesNo(d.connected)),
          h("td", null, formatDateTime(d.last_seen)),
        ),
      );
    }
    wrap.hidden = list.length === 0;
    empty.hidden = list.length > 0;
  }

  async function load(manual: boolean): Promise<void> {
    if (isBusy(refresh)) return;
    setBusy(refresh, true);
    try {
      const list = await ctx.api.listDevices();
      render(list);
      error.set(null);
      if (manual) ctx.announce(`Devices refreshed. ${list.length} enrolled, ${list.filter((d) => d.connected).length} connected.`);
    } catch (err) {
      error.set(errorText(err));
      if (manual) ctx.announce(`Error: ${errorText(err)}`);
    } finally {
      setBusy(refresh, false);
    }
  }
  refresh.addEventListener("click", () => void load(true));

  // --- admin: enroll code ---------------------------------------------------
  const adminError = pageError();
  const generate = h("button", { type: "button" }, "Generate enroll code");
  const codeTitle = uid("enroll-title");
  const codeBody = h("div");
  const codeResult = h("section", { class: "result", hidden: true, tabindex: "-1", "aria-labelledby": codeTitle }, h("h2", { id: codeTitle }, "Enroll code"), codeBody);

  generate.addEventListener("click", async () => {
    if (isBusy(generate)) return;
    setBusy(generate, true);
    adminError.set(null);
    try {
      const { code, expires } = await ctx.api.createEnrollCode();
      clear(codeBody);
      const copyId = uid("enroll-code");
      const ro = readonlyValue(copyId, "Code as text", code);
      codeBody.append(
        h("p", { class: "code-display", "aria-hidden": "true" }, code),
        h("p", { class: "visually-hidden" }, `Code: ${spelled(code)}`),
        ro.root,
        h("div", { class: "actions" }, copyButton(ctx, "enroll code", () => code)),
        h("p", null, `Expires ${formatDateTime(expires)}. Enter it on the new device once; it is exchanged for a device key and then forgotten.`),
      );
      codeResult.hidden = false;
      ctx.announce(`Enroll code: ${spelled(code)}. Expires ${formatDateTime(expires)}.`);
      focusInert(codeResult);
    } catch (err) {
      adminError.set(errorText(err));
      ctx.announce(`Error: ${errorText(err)}`);
    } finally {
      setBusy(generate, false);
    }
  });

  const adminTitle = uid("devices-admin");
  const element = h(
    "section",
    null,
    h("h1", null, "Devices"),
    h("p", { class: "lede" }, "The wearer's renderers. The primary device gets each utterance first; the relay fails over when it does not start in time."),
    h("div", { class: "actions" }, refresh),
    error.el,
    empty,
    wrap,
    h(
      "section",
      { "aria-labelledby": adminTitle },
      h("h2", { id: adminTitle }, "Enroll a new device"),
      h("p", null, "Needs the admin token. The code is short-lived and shown here as plain text so it can be read or copied."),
      h("div", { class: "actions" }, generate),
      adminError.el,
      codeResult,
    ),
  );
  return { element, ready: load(false) };
}
