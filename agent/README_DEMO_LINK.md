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

## The shareable link

The relay is deployed on the GCP demo VM and reachable over HTTPS:

    https://35-224-56-20.sslip.io

That origin serves the real client page, the manifest, the service worker and
`/ws`, with a Let's Encrypt certificate, so a phone can install it as an app.
Details, restart commands and limits: [VM_ONLINE.md](VM_ONLINE.md).

Two demo choices are settled by this deployment:

1. **Exposure path** — a hosted relay on the VM, fronted by Caddy. Not a LAN
   address and not a quick tunnel; the hostname is permanent because the VM's
   IP is reserved and the name is derived from it.
2. **Model** — the VM runs `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on a funded
   trial key. `/api/ziv/model/check` reports `200`, and a scheduled intent makes
   a real call: `tell me to drink` composed **"drink water"**, and all 10 of its
   cells played on the public band. The relay sends
   `chat_template_kwargs: {"enable_thinking": false}` — without it this model
   spends the whole budget in `reasoning` and returns `content: null`. Keyless
   still fires the full turn and labels it `text_echo`; `health.text.last_compose`
   carries the provider's own reason when a call fails. A judge can also use
   their own key in the console's one-shot panel: that path needs nothing
   configured on the VM, and the key is never stored.

Auth is still unset on the VM (`ZIV_RELAY_TOKEN`). With the token set, the
current client cannot connect because it sends no token — a known gap, stated
in the honesty docs. For a judged demo, leaving it unset is the honest choice.

## The honest current status

- The relay and the real client page are verified working together **locally**
  and on the **public HTTPS origin** (service worker controlling, `wss://`
  connected, a live turn rendered 12/12 braille cells, Chrome reports no
  installability errors).
- The VM's relay and Caddy are both systemd units and both `enabled`: a full VM reset
  brought the public URL back in 19 s with no manual step.
- The demo is unauthenticated on purpose for judging.

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
