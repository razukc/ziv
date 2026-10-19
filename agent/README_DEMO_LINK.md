# Try out link — Ziv full demo

This is the operational note for the “Try out” link, not a claim about what is
hosted today. It says what the link must be, what we verified locally, and what
is still missing before a link is shareable from this machine.

## What the full demo needs

The relay is `agent/ziv_server.py`. It serves the real client page from
`agent/ziv_client/index.html` at:

    /ziv_client/index.html

and owns the whole interaction contract:

- `GET /api/ziv/health` — public, no auth, the PWA badge polls this
- `GET /api/ziv/timing` — public, the generated timing module the client
  bootstraps from
- `GET /ziv_client/index.html` — the client page, public
- `WebSocket /ws` — the device transport (optional `?token=` when
  `ZIV_RELAY_TOKEN` is set)
- `POST /api/ziv/message` — bearer-gated when the token is set
- `POST /inject/audio` — bearer-gated when the token is set (keyless
  `{"simulate": "…"}` path goes through the same turn)
- `POST /api/ziv/schedule` — bearer-gated when the token is set
- `GET/DELETE /api/ziv/schedule` — bearer-gated when the token is set
- `GET/POST /api/ziv/inbox` — bearer-gated when the token is set
- `GET/POST /api/ziv/prefs` — bearer-gated when the token is set

That is the full demo shape: page + relay on the same origin, page wired to
`ws://<host>/ws` and `fetch("/api/ziv/health")`, everything else relative to
the same host.

## What we verified locally

On this Windows machine we started `agent/ziv_server.py` on several loopback
ports and exercised the contract directly. Highlights:

- Health answers `200 ok` within seconds of start on the chosen port.
- Scheduling a reminder returns `{"scheduled":true,…}` and the reminder fires
  on the WebSocket without anyone sending a message.
- A WebSocket reader attached to `/ws` sees the reminder arrive as a
  self-naming turn: `reminder: <text>` first, then `z i v` cells, then the
  triple-pulse mark, then the kind cue, then content cells, then the
  `end-of-message` close.
- Filling the replay queue to cap produces HTTP `429` on the next arrival.
- Posting while no band is attached stores the message in the inbox and
  delivers it on the next attach.

Those runs used `ZIV_FAKE_MODEL_SECONDS` shortened so a turn completes fast
enough to verify in a script. The real demo uses the default pace; the
contract is the same.

Evidence lives in the agent log files we created for the run, named like:

    agent/_verify_relay_<port>.log

with the reminder-fire assertions in the run output, not in the repo’s
commit history.

## What is still missing for a shareable link

Right now the verified surface is `127.0.0.1` only. That is “this device” on
the machine that is running the relay, which is not useful to a phone, a judge
on another laptop, or anyone not on this exact session.

To make a real “Try out” link we still need to decide:

1. Which exposure path you want:
   - local LAN address only (same WiFi, phone opens `http://<this-machine-ip>:8787/ziv_client/index.html`)
   - a tunnel from this machine to a public URL
   - a hosted deployment of the relay itself

2. Whether the demo should use the live Nebius Token Factory text model path or
   stay keyless (`text_echo`). Keyless still fires; it is just labelled
   honestly as an echo. The link works either way.

3. Whether you want auth turned on. With `ZIV_RELAY_TOKEN` set, the current
   client page cannot connect because it sends no token. That is a known gap
   in the client, stated in the repo’s honesty docs. For a demo link today,
   leaving the token unset is the honest choice.

## The honest current status

- The relay and the real client page are verified working together on this
  machine, loopback only.
- There is no public URL, tunnel, or hosted deployment attached to this
  session yet.
- If you want a link you can paste into a phone or send to a judge, the next
  move is to choose the exposure path in the list above and stand it up.

## Files that matter for the full demo

- `agent/ziv_server.py` — the relay
- `agent/ziv_client/index.html` — the real client page the relay serves
- `agent/serve_for_preview.py` — optional one-command runner for the preview
  agent if you want to start the relay from a launcher
- `agent/verify_relay.py` — the smoke harness we used to assert the
  reminder-fire contract on a fresh port

Do not treat `public/` as the source of truth for the demo page. That folder
held a static-only copy during earlier static-server experiments. The canonical
client page for the full demo is `agent/ziv_client/index.html`, served by the
relay itself.
