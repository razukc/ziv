# Running the Ziv full demo relay

This is the canonical local run command for the full demo, not the static band.

From the repo root:

    cd agent
    python ziv_server.py

The relay serves the real client page at:

    /ziv_client/index.html

so the full demo URL on this machine is:

    http://127.0.0.1:8787/ziv_client/index.html

For a phone on the same WiFi, replace `127.0.0.1` with this machine’s LAN IPv4
address. `127.0.0.1` means “this device” on the phone itself.

## One-command launcher

If you want a single script instead of running `ziv_server.py` directly:

    python agent/serve_for_preview.py

That starts the relay and waits until `/api/ziv/health` answers `200 ok`, then
prints the URL and the process id. It does not open a browser; use the preview
panel to open the URL it prints.

## What counts as the full demo

- The relay is running.
- The client page is reachable at `/ziv_client/index.html` from the same host
  as the relay.
- The page can open a WebSocket to the same origin.
- The page can fetch `/api/ziv/health`.

If any of those is missing, it is not the full demo — it is only a static page
standing in for the relay.

## Env vars that matter for the demo

- `ZIV_PORT` — which port the relay binds. Default `8787`.
- `ZIV_FAKE_MODEL_SECONDS` — how long a turn pretends to wait for a model.
  Shorten it for scripted verification; the contract is the same.
- `NEBIUS_API_KEY` — optional. Without it, scheduled intents fire verbatim as
  `text_echo`. With it, the relay calls the configured text model.
- `ZIV_RELAY_TOKEN` — optional. When set, auth is on and the current client
  page cannot connect. That is a known client gap, not something to paper over
  for a demo link today.

## Verified locally

We started the relay on several loopback ports and verified:

- `/api/ziv/health` answers `200 ok`
- scheduling a reminder returns `{"scheduled":true,…}`
- a WebSocket client attached to `/ws` receives the reminder as a self-naming
  turn: `reminder: <text>`, then `z i v` cells, then the triple-pulse mark,
  then the kind cue, then content cells, then the `end-of-message` close
- filling the replay queue to cap returns HTTP `429` on the next arrival
- messages posted with no band attached are stored and delivered on the next
  attach

Evidence is in the temporary run logs we created for those checks, named like
`agent/_verify_relay_<port>.log`. Those are session artifacts, not part of the
repo’s committed history.

## What is not done yet

A shareable “Try out” link is not done from this machine yet. Verified so far
is loopback only. The missing piece is exposure: LAN address, tunnel, or hosted
deployment, plus a decision on whether the demo should be keyless or use the
live Nebius text model path.

Do not treat `public/` as the demo page source. That folder holds a static-only
copy from earlier experiments. The real client page for the full demo is
`agent/ziv_client/index.html`, served by the relay.
