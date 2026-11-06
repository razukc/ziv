// One polite live region for the whole console. Only user-initiated results
// and state changes of items the user acted on go through here; polling
// never announces, and a repeat within a second is dropped so a braille
// display is not flooded.

let region: HTMLElement | null = null;
let lastText = "";
let lastAt = 0;
let pending: ReturnType<typeof setTimeout> | null = null;

export function liveRegion(): HTMLElement {
  if (region && region.isConnected) return region;
  region = document.getElementById("live-status");
  if (!region) {
    region = document.createElement("div");
    region.id = "live-status";
    region.className = "visually-hidden";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    region.setAttribute("aria-atomic", "true");
    document.body.appendChild(region);
  }
  return region;
}

export function announce(text: string): void {
  const now = Date.now();
  if (text === lastText && now - lastAt < 1000) return;
  lastText = text;
  lastAt = now;
  const el = liveRegion();
  // Clear first so an identical message later is still spoken; the short
  // delay lets assistive tech see the change. Nothing depends on its length.
  el.textContent = "";
  if (pending) clearTimeout(pending);
  pending = setTimeout(() => {
    el.textContent = text;
    pending = null;
  }, 40);
}

/** For tests: the text currently in the region (after the delay). */
export function liveText(): string {
  return liveRegion().textContent ?? "";
}
