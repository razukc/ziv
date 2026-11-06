import type { Health } from "../generated/wire.ts";
import { clear, h } from "../dom.ts";
import type { AppContext, View } from "../router.ts";
import { dl, errorText, isBusy, pageError, setBusy } from "./common.ts";

export function healthView(ctx: AppContext): View {
  const error = pageError();
  const body = h("div", { id: "health-body" });
  const refresh = h("button", { type: "button", class: "secondary" }, "Refresh");

  async function load(manual: boolean): Promise<void> {
    if (isBusy(refresh)) return;
    setBusy(refresh, true);
    try {
      const health = await ctx.api.getHealth();
      render(health);
      error.set(null);
      if (manual) ctx.announce(`Health refreshed. ${health.devices_connected} devices connected, ${health.schedule_pending} scheduled.`);
    } catch (err) {
      error.set(errorText(err));
      if (manual) ctx.announce(`Error: ${errorText(err)}`);
    } finally {
      setBusy(refresh, false);
    }
  }

  function render(health: Health): void {
    clear(body);
    const outbox = Object.entries(health.outbox);
    const caps = Object.entries(health.caps);
    body.append(
      dl([
        ["Status", health.status],
        ["Relay version", health.version],
        ["Spec version", String(health.spec_version)],
        ["Wire version", String(health.wire_version)],
        ["Devices connected", String(health.devices_connected)],
        ["Schedule entries pending", String(health.schedule_pending)],
        ["Last compose", health.compose ? Object.entries(health.compose).map(([k, v]) => `${k} ${String(v)}`).join(", ") : "none recorded"],
      ]),
      countsTable("Outbox by state", "State", outbox),
      countsTable("Caps and counters", "Name", caps),
    );
  }

  function countsTable(caption: string, nameHeader: string, rows: [string, number | undefined][]): HTMLElement {
    const table = h(
      "table",
      null,
      h("caption", null, caption),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, nameHeader), h("th", { scope: "col" }, "Count"))),
      h("tbody", null, ...rows.map(([k, v]) => h("tr", null, h("th", { scope: "row" }, k.replaceAll("_", " ")), h("td", null, String(v ?? 0))))),
    );
    return h("div", { class: "table-wrap" }, table);
  }

  refresh.addEventListener("click", () => void load(true));

  const element = h(
    "section",
    null,
    h("h1", null, "Health"),
    h("p", { class: "lede" }, "Counts only; the relay never puts message text here. This route needs no token."),
    h("div", { class: "actions" }, refresh),
    error.el,
    body,
  );
  return { element, ready: load(false) };
}
