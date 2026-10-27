# Hosted relay recipe draft — keyless demo

Status: recipe draft only. Not deployed. Not a scaffold. BYOK is wired as a
one-shot compose (`POST /api/ziv/compose`) — a judge-supplied key is used for
one call and is never stored, scheduled, or written into the environment.

## 1) What a hosted build actually needs

The full demo is one process: `agent/ziv_server.py` is both the API and the page.

### Entry point
- `python agent/ziv_server.py`
- Under the hood it calls `uvicorn.run(app, host="0.0.0.0", port=ZIV_PORT)`, default port `8787`.
- It is a single file that imports everything from the same repo; it is not a package you install.

### Files a host needs
From the repo root, the host needs the tree that `agent/ziv_server.py` actually reads at runtime:
- `agent/ziv_server.py`
- `agent/ziv_client/index.html` (served by `GET /ziv_client/index.html` from the same process)
- `tools/haptic_timing_gen.py` (imported by the relay at startup)
- `tools/haptic_timing_gen.py` must be the generated consumer, not a stale block; the timing drift guard already enforces that locally.

### Python deps
Use `agent/requirements.txt`:
```
openai>=1.0.0
fastapi>=0.104.0
uvicorn>=0.24.0
websockets>=12
pydantic>=2.0.0
python-dotenv>=1.0.0
httpx>=0.27
```

### Install command
A typical hosted-worker install from the repo root is:
```
pip install -r agent/requirements.txt
python agent/ziv_server.py
```

If the host has a separate build-vs-run directory, the app is not importable unless the working directory or Python path covers both `agent/` and `tools/`. That is the exact concern to resolve before claiming the build is portable.

## 2) Env vars the relay reads

### Startup-time / wiring
- `ZIV_PORT` — default `8787`. Host ports may be assigned externally; if so, set this.
- `ZIV_FAKE_MODEL_SECONDS` — default `3.0`. Controls the fake-model wait in the demo beat.
- `ZIV_RELAY_TOKEN` — default empty = open. Set to lock the relay down. For the keyless demo link, leave it unset unless you want auth on.
- `NEBIUS_API_KEY` — default empty. If unset, `agent_path_configured()` is False and no live call is attempted; scheduled intents fire verbatim as `text_echo`. The judge-key path (`POST /api/ziv/compose`) does not need it: the key travels in `X-Nebius-Key` for one request.
- `NEBIUS_BASE_URL` — default `https://api.tokenfactory.nebius.com/v1/`. Only matters if `NEBIUS_API_KEY` is set.
- `ZIV_TEXT_MODEL` — default `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`. Only matters if `NEBIUS_API_KEY` is set.

### What stays unset for a keyless demo
For the default keyless demo link, leave these empty:
- `NEBIUS_API_KEY`
- `ZIV_RELAY_TOKEN` (unless you explicitly want auth on)

### What that means in behavior
- The scheduled-reminder / intent path does not call a model; it fires verbatim and the wire log labels it `text_echo`.
- The Omni audio seam (`POST /inject/audio`) answers 503 when no audio-capable endpoint is configured.
- The client page, timing, health, schedule, inbox, and message routes still work.
- The demo still proves the whole turn shape, the queue + 429 + redial, and the always-on reminder beat — without any key.

### Health separates wiring from proof
`GET /api/ziv/health` currently returns, among other things:
- `auth` — whether `ZIV_RELAY_TOKEN` is set
- `model` — `ZIV_TEXT_MODEL`
- `configured` — `agent_path_configured()`: key + model present, so a call can be *attempted*
- `available` — `agent_path_available()`: `null` until a real compose is attempted, then that attempt's outcome. It is not a key check — an unfunded key reports `available: false` with the provider's status in `last_compose`
- `last_compose` — `{ok, status, error, detail, model, at}` for the last scheduled compose attempt, or `null`. Content-free: counts and provider status only, never the line

For a keyless hosted demo, that is fine and even useful: it makes the default “no model wired” state visible in the operator view. It is worth one honest check before shipping: confirm the health payload only exposes counts/telemetry/wiring and never message text, reminders, or inbox content. The current public claim is that it does; this recipe should not be shipped until that claim is re-verified on the deployed instance.

## 3) Bind/origin/URL assumptions to check before hosting

### Bind address
The script binds to `0.0.0.0`, not `127.0.0.1`. That is already the right shape for a hosted process. The demo docs still describe the URL as `http://<lan-ip>:8787/ziv_client/index.html`, so the live docs still say “LAN address” and need updating if the link becomes a public host.

### Client page is relative
`agent/ziv_client/index.html` uses a relative WS URL against the page’s own origin for `/ws` and relative HTTP paths for `/api/ziv/*`. That is good for hosting: the same deployed origin should work for both the page and the relay. Do not assume a hardcoded base URL in the client; verify the deployed origin actually resolves both.

### Auth story is protocol-level, not origin-level
The relay’s optional auth is a shared token (`?token=` on WS, `Authorization: Bearer` on content routes), not a baked origin allowlist. If you host the demo publicly and leave `ZIV_RELAY_TOKEN` unset, the link is open; if you set it, the current client page cannot connect without a bespoke client build. That is the honest tradeoff to state plainly for a judge link.

### HTTPS / public origin
If the chosen host serves HTTPS and the relay runs behind it, the page origin will be TLS and the WS scheme will be `wss://`. The client code should handle that via relative URLs; still, verify the deployed origin does not break WS negotiation or CORS for the page’s own requests.

## 4) Durable-link concern: sleep / wake / idle WS

This is the real hosted-demo risk, not the deploy mechanics.

- The full demo needs the FastAPI process reachable and its `/ws` usable. If the host sleeps the worker after idle traffic, a judge who opens the page during a cold period may hit a slow wake or a refused WS until the worker is back.
- For a demo link, that is the difference between “reachable when the laptop is off” and “reachable and pleasant on first open.”
- The right mitigation depends on the host choice:
  - a paid always-on worker avoids idle spin-down;
  - a free tier that sleeps may still satisfy the literal request (“reachable when the laptop is off”) but with a cold-start caveat that should be stated in the demo link notes.

So the recipe should not claim “durable link” without naming the host’s idle behavior and whether the cheap/free tier keeps `/ws` usable.

## 5) Current honest gaps before this becomes a real deploy

1. **Host decision not made.** The leaned-toward target is a managed Python web service host (Render-style), with a cheap VPS as the durable fallback. Neither has been selected or provisioned. A tunnel is explicitly not the answer for the “laptop off” requirement.

2. **Host can actually run this as-is.** The repo has no deploy manifest and no separate package entrypoint. The only proven start command is `python agent/ziv_server.py` from the repo root with `agent/` and `tools/` importable. Before claiming a hosted build, verify the chosen host’s layout supports that import layout without hacking the repo into a package.

3. **No secrets are required for the keyless demo, but the live model path is still a conditional env var.** If the demo later wants the live `text_live` beat, it needs `NEBIUS_API_KEY` (and optionally `ZIV_TEXT_MODEL`) set in the host’s secret store. That is not wired now, and this recipe intentionally leaves it out.

4. **Public docs still describe LAN-only exposure.** README, demo docs, and status notes describe `http://<lan-ip>:8787/ziv_client/index.html`. If the link becomes hosted, those should be updated to the real public URL and to the cold-start/auth caveats.

5. **Auth-on vs auth-off not decided for the public link.** If the demo link is meant to be judge-facing and public, leaving `ZIV_RELAY_TOKEN` unset is the simplest current path, but then the link is open. If it should be gated, the client page needs a bespoke path or a documented token flow; the current client cannot connect with `ZIV_RELAY_TOKEN` set.

6. **Scope of the demo beat not finalized.** Confirm whether the judge-facing demo is the keyless path only, or whether the live Nebius model beat is part of what judges should see. Recommendation stands: host the keyless beat as the default link; treat the live model beat as an optional env switch, not the hosted demo centerpiece and not BYOK.

## 6) Verification steps for the hosted link (once it exists)

These are the smallest checks that prove the link is the real full demo, not a static page:

1. Health reachable over the public URL:
   - `GET /api/ziv/health` returns `200`.
2. Page served over the public URL:
   - `GET /ziv_client/index.html` returns `200` and the real client page content.
3. Keyless demo path works:
   - `POST /api/ziv/message` with a text body returns an accepted or queued response (or stores it if no device is attached).
   - `POST /api/ziv/schedule` with a future `fire_at` returns `{"scheduled":true,...}`.
4. WebSocket beat over the public URL:
   - A WS client connecting to `wss://<public-origin>/ws` receives a scheduled reminder as a self-naming turn: prefix mark, cue, processing ticks, content cells, close, queue release.
5. Optional durable-link check:
   - If the host has an idle-sleep tier, verify whether an idle period breaks the first WS connect or only adds a cold-start delay, and record that caveat explicitly in the demo link notes.
6. Model wiring:
   - `GET /api/ziv/model/check` answers `200` with a `sample` when the key works, and `502` with the provider's own `provider_status`/`detail` when it does not.
   - `POST /api/ziv/compose` with a judge-supplied `X-Nebius-Key` plays one `text_live` turn; a bad key returns the provider's status without the key in the body.

If any of those fail on the deployed URL, the link is not yet the hosted full demo; treat it as a build issue, not a verification artifact.

## 7) What is not in scope here

- No key storage: BYOK is one request, not a saved credential.
- No new package scaffolding.
- No actual deploy in this pass.
- No decision on the final host; this is the recipe surface plus the gaps that block a real deploy.
