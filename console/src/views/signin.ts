import { ApiError } from "../api.ts";
import { errorSlot, field, h, uid } from "../dom.ts";
import type { AppContext, View } from "../router.ts";
import { forgetToken, setToken } from "../session.ts";
import { errorText, isBusy, setBusy } from "./common.ts";

export function signinView(ctx: AppContext): View {
  const input = h("input", { type: "password", autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
  const token = field(input, {
    label: "Token",
    hint: "A sender token or the admin token. It is held in this tab only and forgotten when the tab closes.",
    required: true,
  });

  const showId = uid("show-token");
  const show = h("input", { type: "checkbox", id: showId });
  show.addEventListener("change", () => {
    input.type = show.checked ? "text" : "password";
  });

  const submit = h("button", { type: "submit" }, "Sign in");
  const form = h("form", { novalidate: true, "aria-labelledby": "signin-title" });
  const formError = errorSlot(form);
  form.append(
    token.root,
    h("div", { class: "choice" }, show, h("label", { for: showId }, "Show the token while typing")),
    h("div", { class: "actions" }, submit),
    formError.el,
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    token.setError(null);
    formError.set(null);
    const value = input.value.trim();
    if (!value) {
      token.setError("Enter a token.");
      ctx.announce("Error: enter a token.");
      input.focus();
      return;
    }
    setBusy(submit, true);
    setToken(value);
    try {
      await ctx.spec(); // any valid token can read the spec; this proves the token
      ctx.announce("Signed in.");
      ctx.navigate("send");
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        forgetToken();
        token.setError(`The relay did not accept this token. ${err.detail}`);
        ctx.announce(`Error: the relay did not accept this token. ${err.detail}`);
        input.focus();
      } else {
        // Kept: the token may be fine and the relay merely unreachable.
        formError.set(`Token kept for this tab, but the relay could not confirm it. ${errorText(err)}`);
        ctx.announce(`Token kept, but the relay could not confirm it. ${errorText(err)}`);
      }
    } finally {
      setBusy(submit, false);
    }
  });

  const element = h(
    "section",
    null,
    h("h1", { id: "signin-title" }, "Sign in"),
    h(
      "p",
      { class: "lede" },
      ctx.signedIn()
        ? "You are signed in. Paste a different token to replace it, or use Forget this token in the banner."
        : "Paste the token you were given. Sender tokens can send and read; the admin token also manages devices and senders.",
    ),
    h("p", null, `This console talks to ${ctx.api.baseUrl || "the relay on this origin"}.`),
    form,
  );
  return { element };
}
