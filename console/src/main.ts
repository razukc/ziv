// The console shell: banner, navigation, one main region, one live region,
// and a hash router that mounts a view into main. Views never touch the
// shell; the shell never touches the relay except to verify a token.

import { Api, ApiError, describeReason, type TimingSpec } from "./api.ts";
import { announce, liveRegion } from "./announce.ts";
import { h, clear, focusInert, setText } from "./dom.ts";
import { currentToken, forgetToken, onSessionChange } from "./session.ts";
import {
  PUBLIC_ROUTES,
  ROUTES,
  ROUTE_TITLES,
  hashFor,
  routeFromHash,
  type AppContext,
  type Route,
  type View,
  type ViewFactory,
} from "./router.ts";
import { signinView } from "./views/signin.ts";
import { sendView } from "./views/send.ts";
import { utterancesView } from "./views/utterances.ts";
import { scheduleView } from "./views/schedule.ts";
import { prefsView } from "./views/prefs.ts";
import { devicesView } from "./views/devices.ts";
import { sendersView } from "./views/senders.ts";
import { healthView } from "./views/health.ts";

const API_BASE = typeof __API_BASE__ === "string" ? __API_BASE__ : "";

const VIEWS: Record<Route, ViewFactory> = {
  signin: signinView,
  send: sendView,
  utterances: utterancesView,
  schedule: scheduleView,
  prefs: prefsView,
  devices: devicesView,
  senders: sendersView,
  health: healthView,
};

export interface Shell {
  /** The mounted view, for tests that wait on its `ready`. */
  current(): View | null;
  route(): Route | null;
  /** Unmount the view and stop listening; the shell is not reusable after. */
  stop(): void;
}

export function start(root: HTMLElement = document.body): Shell {
  const api = new Api({ baseUrl: API_BASE, token: currentToken });

  let specPromise: Promise<TimingSpec> | null = null;
  const ctx: AppContext = {
    api,
    announce,
    navigate: (route) => {
      window.location.hash = hashFor(route);
    },
    signedIn: () => Boolean(currentToken()),
    spec: () => {
      if (!specPromise) {
        specPromise = api.getSpec().catch((err: unknown) => {
          specPromise = null;
          throw err;
        });
      }
      return specPromise;
    },
  };

  // --- shell --------------------------------------------------------------

  const skip = h("a", { class: "skip-link", href: "#main" }, "Skip to content");
  const sessionText = h("span", { id: "session-state" });
  const forget = h(
    "button",
    {
      type: "button",
      class: "secondary",
      "aria-describedby": "session-state",
      on: {
        click: () => {
          forgetToken();
          specPromise = null;
          announce("Token forgotten. Signed out.");
          ctx.navigate("signin");
        },
      },
    },
    "Forget this token",
  );
  const banner = h(
    "header",
    { class: "banner", role: "banner" },
    h("p", { class: "brand" }, "Ziv console", h("small", null, "haptic message channel")),
    h("div", { class: "session" }, sessionText, forget),
  );

  const navLinks = new Map<Route, HTMLAnchorElement>();
  const nav = h(
    "nav",
    { class: "console", "aria-label": "Console" },
    h(
      "ul",
      null,
      ...ROUTES.map((route) => {
        const a = h("a", { href: hashFor(route) }, ROUTE_TITLES[route]);
        navLinks.set(route, a);
        return h("li", null, a);
      }),
    ),
  );

  const main = h("main", { id: "main", tabindex: "-1" });
  const footer = h(
    "footer",
    { class: "about" },
    h("p", null, `Talks to ${API_BASE ? API_BASE : "the relay on this origin"}. The console never plays haptics; it is not a renderer.`),
  );

  clear(root);
  root.append(skip, banner, nav, main, footer);
  liveRegion();

  const refreshSession = (): void => {
    const signed = ctx.signedIn();
    setText(sessionText, signed ? "Signed in. Token held in this tab only." : "Not signed in.");
    forget.hidden = !signed;
  };
  refreshSession();
  onSessionChange(refreshSession);

  // --- routing ------------------------------------------------------------

  let current: { route: Route; view: View } | null = null;

  const show = (requested: Route): void => {
    const route = ctx.signedIn() || PUBLIC_ROUTES.has(requested) ? requested : "signin";
    if (current?.route === route) return;
    current?.view.unmount?.();
    clear(main);
    let view: View;
    try {
      view = VIEWS[route](ctx);
    } catch (err) {
      view = { element: h("section", null, h("h1", null, "Something broke"), h("p", { class: "form-error" }, `Error: ${describe(err)}`)) };
    }
    if (route === "signin" && requested !== "signin") {
      view.element.prepend(h("p", { class: "notice" }, `Sign in to open ${ROUTE_TITLES[requested]}.`));
    }
    main.appendChild(view.element);
    current = { route, view };
    for (const [r, a] of navLinks) {
      if (r === route) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    document.title = `${ROUTE_TITLES[route]} – Ziv console`;
    view.mount?.();
    const heading = view.element.querySelector("h1");
    if (heading) focusInert(heading);
  };

  const onHash = (): void => {
    const route = routeFromHash(window.location.hash);
    if (route) show(route);
    else if (window.location.hash === "" || window.location.hash === "#") show(ctx.signedIn() ? "send" : "signin");
    // any other hash (#main) is an in-page target; leave the view alone
  };
  window.addEventListener("hashchange", onHash);
  onHash();
  return {
    current: () => current?.view ?? null,
    route: () => current?.route ?? null,
    stop: () => {
      window.removeEventListener("hashchange", onHash);
      current?.view.unmount?.();
      current = null;
    },
  };
}

function describe(err: unknown): string {
  if (err instanceof ApiError) return `${describeReason(err.reason)}: ${err.detail}`;
  return err instanceof Error ? err.message : String(err);
}

if (typeof document !== "undefined" && document.body && !document.body.dataset["zivTest"]) {
  start();
}
