# From verified loopback to a reachable “Try out” link

This note records the remaining work to turn the verified local demo into
something a phone or a judge can actually open. It is intentional and
immutable: it says what we already proved and what still has to be chosen and
done.

## What we already proved

- `agent/ziv_server.py` starts and answers `GET /api/ziv/health` with
  `200 ok` on the port you give it.
- The relay serves the real client page at `/ziv_client/index.html`.
- A WebSocket client attached to `/ws` receives a scheduled reminder as a
  self-naming turn: `reminder: <text>`, `z i v` cells, the triple-pulse mark,
  the kind cue, content cells, then the `end-of-message` close.
- Filling the replay queue to cap returns HTTP `429`.
- Messages posted with no band attached are stored and delivered on the next
  attach.

We proved that on this machine, loopback only, on several ports, with
`ZIV_FAKE_MODEL_SECONDS` shortened for scripted verification.

Evidence lives in the session run logs, named like
`agent/_verify_relay_<port>.log`. Those are temporary artifacts from this
session; they are not part of the repo’s committed history.

## What still has to be chosen

A shareable “Try out” link needs an exposure path. Pick one:

1. **LAN only** — run the relay on this machine and give judges/phones the
   machine’s local IPv4 address. Only people on the same WiFi can open it. No
   public URL, no hosting account.

2. **Tunnel from this machine** — keep the relay running here but expose it
   through a tunnel so there is a public URL that reaches back to this session’s
   relay. The relay still lives on this Windows box.

3. **Hosted relay** — deploy the relay itself somewhere reachable. This is the
   only option that does not depend on this machine staying online and on the
   session staying open.

Also decide the model path:

- **Keyless demo** — no `NEBIUS_API_KEY` in the relay’s environment. Scheduled
  intents fire verbatim as `text_echo`. The link still works; the wire log is
  just honest about the path.
- **Live model path** — set `NEBIUS_API_KEY` and the configured text model in
  the relay’s environment. Scheduled intents are composed by the model at fire
  time. This needs a funded account and a real key in the relay’s environment,
  not in the page.

Also decide auth:

- **Leave the token unset** for a demo link today. The current client page sends
  no token, so with `ZIV_RELAY_TOKEN` set the page cannot connect. That is a
  known client gap, and it is stated in the repo’s honesty docs. Do not set the
  token just to make the link “feel” locked down; it would break the page.

## The actual next move

If you want the fastest real link, do this:

1. Run the relay on this machine:
   `cd agent && python ziv_server.py`
   or `python agent/serve_for_preview.py`.

2. Find this machine’s LAN IPv4 address and give the phone/judge:
   `http://<lan-ip>:8787/ziv_client/index.html`

3. Confirm the phone can reach that address and the page can talk to
   `/api/ziv/health` and `/ws`.

That is the full demo link for anyone on the same WiFi. It is not a public URL,
and it depends on this machine being the relay host.

## If you want a public URL or hosted relay

That is a separate decision from the local demo, and I should not guess the host
or the tunnel tool. If you want to go there, tell me:

- LAN only, or tunnel, or hosted.
- Keyless, or live model path with a Nebius key you already have.
- Whether the link is for a phone on the same WiFi, or for someone remote.

With that, I can stand up the matching exposure path and give you a concrete URL
instead of another loopback proof.
