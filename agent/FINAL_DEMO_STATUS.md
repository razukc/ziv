# Final status — Ziv full demo backend + reachable URL

This is the final assessment for the “full demo / Try out links” work in this
session. It is written to be read as a status artifact, not as a claim that a
public link exists today.

## What we were asked to do

Add the missing piece for a full “Try out” experience: the backend plus a
reachable URL. The repo already had a static-only page served by a Caddy file
server. The full demo needs the Python relay `agent/ziv_server.py` running and
reachable, plus the real client page `agent/ziv_client/index.html` served from
the same origin.

## What we actually verified

We verified the backend + real page combo, locally, on loopback. In several
fresh runs on several fresh ports we confirmed:

- `agent/ziv_server.py` starts and answers `GET /api/ziv/health` with `200`.
- `GET /ziv_client/index.html` is served by the relay itself.
- Scheduling a reminder returns `{"scheduled":true,...}`.
- A WebSocket client attached to `/ws` receives the reminder as a self-naming
  turn: `reminder: <text>`, then `z i v` cells, then the triple-pulse mark,
  then the kind cue, then content cells, then the `end-of-message` close.
- Filling the replay queue to cap returns HTTP `429`.
- Messages posted with no band attached are stored and delivered on the next
  attach.

Evidence is in the session run logs we created for those checks, named like
`agent/_verify_relay_<port>.log` and `agent/_verify_relay_smoke_<port>.log`.
Those are temporary session artifacts; they are not part of the repo’s
committed history.

The smoke baseline also now lives in a reusable script:
`agent/verify_relay_smoke.py`. That script asserts health + the served client
page. The WS reminder-fire contract is in `agent/verify_relay.py --demo`.

## What is still missing for a shareable link

A shareable “Try out” link is **not done yet**. The verified surface is
`127.0.0.1` only. That is “this device” on the machine running the relay, so a
phone, a judge on another laptop, or anyone remote cannot use it from that
address.

To make a real link we still need to decide and do one of these:

1. LAN address only — run the relay here and give the machine’s local IPv4
   address. Same WiFi only.
2. Tunnel from this machine — a public URL that reaches back to this session’s
   relay. The relay still lives on this Windows box.
3. Hosted relay — deploy the relay itself somewhere reachable. This is the only
   option that does not depend on this machine staying online.

We also still need to decide the model path and auth posture for the link:

- Keyless is fine for the demo today; the relay fires verbatim and labels it
  `text_echo`.
- Live model path is possible if you want the real Nebius text-model beat, but
  that needs `NEBIUS_API_KEY` in the relay’s environment.
- With `ZIV_RELAY_TOKEN` set, the current client page cannot connect. That is a
  known client gap, not something to paper over for the link.

## Files we added or updated for this work

- `agent/verify_relay.py` — full demo verification harness with the WS
  reminder-fire assertion.
- `agent/verify_relay_smoke.py` — lighter smoke baseline: health + served client
  page.
- `agent/serve_for_preview.py` — optional one-command launcher if you want to
  start the relay from a preview launcher instead of running `ziv_server.py`
  directly.
- `agent/RUN_FULL_DEMO.md` — the canonical local run command and what counts as
  the full demo.
- `agent/GET_READY_FOR_TRY_OUT.md` — the remaining decision list before a link
  is shareable.
- `agent/README_DEMO_LINK.md` — the demo-link contract plus current status and
  the one missing piece.
- `agent/FINAL_DEMO_STATUS.md` — this file.

## What is not claimed

We do not claim a public URL today. We do claim the backend + real page combo is
verified working together on this machine, loopback only. The gap is exposure,
not functionality.

## If you want to close the gap now

Pick one path and tell me which:

- Stand up the LAN link now: run the relay, find the LAN address, verify the
  page and health and `/ws` are reachable from that address, and give you the
  concrete URL.
- Stand up a tunnel now: expose this machine’s relay through a public tunnel and
  verify the same things through the tunnel URL.
- Set up the live model path: put `NEBIUS_API_KEY` in the relay’s environment
  and verify a scheduled intent fires with the real model path.

The honest remaining limitation is that none of those is done yet from this
session. Everything after “the relay starts and the page is served” is a
decision + an exposure step, not another backend proof.
