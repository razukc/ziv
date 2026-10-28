// Minimal PWA shell for the Ziv phone band client.
//
// Keep this thin on purpose: the relay UI is the product, and the relay's
// /api/ziv/* and /ws paths are live server resources, not app shell. We only
// cache the static client shell so the installable app can start from a fresh
// launch without the phone needing the Relay online for the chrome itself.

const CACHE = "ziv-phone-band-v19";
const SHELL = [
  "./index.html",
  "./manifest.json",
  "./ziv_icon.svg",
  "./ziv_icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url, self.location.origin);

  // Leave the relay's live paths alone.
  if (url.pathname.startsWith("/api/ziv/") || url.pathname === "/ws") {
    return;
  }

  // Static shell: serve from cache, fall back to network.
  if (SHELL.some((p) => url.pathname.endsWith(p))) {
    e.respondWith(
      caches.match(e.request).then((cached) => {
        const fromCache = cached || fetch(e.request).then((r) => {
          if (r.ok) {
            const clone = r.clone();
            caches.open(CACHE).then((c) => c.put(e.request, clone));
          }
          return r;
        });
        return fromCache;
      })
    );
    return;
  }

  // Anything else that already starts with our sub-path is not part of the
  // installable app shell: leave it alone so the relay's live assets and the
  // parent server's other routes are never intercepted.
  if (url.pathname.startsWith("/api/ziv/") || url.pathname === "/ws") {
    return;
  }
});
