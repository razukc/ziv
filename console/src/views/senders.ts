import { clear, errorSlot, field, focusInert, h, uid } from "../dom.ts";
import type { AppContext, View } from "../router.ts";
import type { SenderScope } from "../api.ts";
import { copyButton, dl, errorText, isBusy, readonlyValue, setBusy } from "./common.ts";

export function sendersView(ctx: AppContext): View {
  const labelInput = h("input", { type: "text", maxlength: "40", autocomplete: "off" });
  const label = field(labelInput, { label: "Label", hint: "Who this token is for, up to 40 characters. Shown to you, never played.", required: true });

  const scopes: { scope: SenderScope; input: HTMLInputElement; text: string }[] = [
    { scope: "send", input: h("input", { type: "checkbox", id: uid("scope"), checked: true }), text: "send: submit utterances, schedule, set preferences" },
    { scope: "read", input: h("input", { type: "checkbox", id: uid("scope"), checked: true }), text: "read: list utterances, schedule, devices, preferences" },
  ];
  const scopesErrorId = uid("scopes-error");
  const scopesError = h("p", { id: scopesErrorId, class: "field-error" });
  const scopeSet = h(
    "fieldset",
    { "aria-describedby": scopesErrorId },
    h("legend", null, "Scopes"),
    ...scopes.map((s) => h("div", { class: "choice" }, s.input, h("label", { for: s.input.id }, s.text))),
    scopesError,
  );

  const submit = h("button", { type: "submit" }, "Create token");
  const form = h("form", { novalidate: true, "aria-labelledby": "senders-title" });
  const formError = errorSlot(form);
  form.append(label.root, scopeSet, h("div", { class: "actions" }, submit), formError.el);

  const resultTitle = uid("sender-result");
  const resultBody = h("div");
  const result = h("section", { class: "result", hidden: true, tabindex: "-1", "aria-labelledby": resultTitle }, h("h2", { id: resultTitle }, "Token created"), resultBody);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    label.setError(null);
    formError.set(null);
    scopesError.textContent = "";
    const labelValue = labelInput.value.trim();
    const chosen = scopes.filter((s) => s.input.checked).map((s) => s.scope);
    if (!labelValue) {
      label.setError("Enter a label.");
      ctx.announce("Error: enter a label.");
      labelInput.focus();
      return;
    }
    if (chosen.length === 0) {
      scopesError.textContent = "Error: choose at least one scope.";
      ctx.announce("Error: choose at least one scope.");
      scopes[0]?.input.focus();
      return;
    }
    setBusy(submit, true);
    try {
      const created = await ctx.api.createSender({ label: labelValue, scopes: chosen });
      const senderId = created.sender ?? created.id ?? "(no id returned)";
      clear(resultBody);
      const ro = readonlyValue(uid("sender-token"), "Token", created.token);
      resultBody.append(
        h("p", { class: "notice" }, "Shown once. The relay keeps only a hash; copy it now and hand it over privately."),
        dl([
          ["For", labelValue],
          ["Sender id", h("span", { class: "secret" }, senderId)],
          ["Scopes", chosen.join(", ")],
        ]),
        ro.root,
        h("div", { class: "actions" }, copyButton(ctx, "token", () => created.token)),
      );
      result.hidden = false;
      labelInput.value = "";
      ctx.announce(`Token created for ${labelValue}. It is shown once; copy it now.`);
      focusInert(result);
    } catch (err) {
      result.hidden = true;
      formError.set(errorText(err));
      ctx.announce(`Error: ${errorText(err)}`);
    } finally {
      setBusy(submit, false);
    }
  });

  const element = h(
    "section",
    null,
    h("h1", { id: "senders-title" }, "Senders"),
    h("p", { class: "lede" }, "Mint a scoped bearer token for a contact, a service or the agent. Needs the admin token."),
    form,
    result,
  );
  return { element };
}
