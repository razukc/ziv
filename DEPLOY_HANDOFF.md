# Hosted demo handoff — Ziv relay on Render (keyless, auth off)

This is the handoff that turns the recipe into an actual hosted link path.

Status: host-specific build plan + verification checklist, ready to run from this machine.
Not deployed yet from here unless the Deploy surface below is available.

## 1) What we are deploying

One process. The full demo is `agent/ziv_server.py`. It is both:
- the API/WS relay, and
- the server of the real client page at `/ziv_client/index.html`.

There is no separate frontend build, no static-site host, and no deploy manifest yet.
The only proven start command from the repo root is:

```
pip install -r agent/requirements.txt
python agent/ziv_server.py
```

Under the hood that runs `uvicorn.run(app, host="0.0.0.0", port=ZIV_PORT)` with
default port `8787`.

## 2) What Render actually needs from this repo

Render Web Services need three things:
- a Python dependency file it can install,
- a start command that binds to `$PORT` on `0.0.0.0`,
- the files the app imports/serves at runtime.

For this repo, that means:

### Dependency file
Render will install from `agent/requirements.txt`.

### Entrypoint problem we have
The repo’s proven entrypoint is `python agent/ziv_server.py`, run from the repo root.
That works because `agent/` and `tools/` are on `sys.path` by runtime path hacking inside
`agent/ziv_server.py`.

Render does not run from the repo root by default in the same way a local `cd` does.
So the real question for a host-specific build is not “does it run with uvicorn” —
it is “can the deployed working directory and Python path make `agent.ziv_server` importable,
and can it find `tools/haptic_timing_gen.py`?”

There are two honest shapes that solve that without inventing a package:

- **Shape A — keep the repo as-is and point Render at `agent/` as the root.**
  If Render’s service root can be set to the `agent/` directory, then
  `python ziv_server.py` can be the start command, provided `tools/` is still importable
  from there. That depends on how `ziv_server.py` resolves `tools/` relative to itself,
  which it already does via `Path(__file__).resolve().parents[1]`.

- **Shape B — keep the repo root as the service root and use a thin wrapper start command.**
  Something like:
  ```
  pip install -r agent/requirements.txt
  python -c "import sys; sys.path.insert(0, 'agent'); sys.path.insert(0, 'tools'); import ziv_server"
  ```
  is not the real deploy shape because `ziv_server.py` is a script with a `__main__` block,
  not a library entrypoint. The honest version is a small wrapper script whose only job is
  to make the repo layout importable and then run the real file.

The point of this handoff is to make that blocker explicit before claiming a hosted build
works. Do not say “it deploys” until the deployed working directory has been checked against
the actual `sys.path` dance in `agent/ziv_server.py`.

### Files the app needs at runtime
- `agent/ziv_server.py`
- `agent/ziv_client/index.html`
- `tools/haptic_timing_gen.py`

### Start command shape for Render
If the service root is arranged so `agent/ziv_server.py` is the runnable entry point:

```
pip install -r agent/requirements.txt
python agent/ziv_server.py
```

and the app reads `$PORT` if Render assigns one. Right now `agent/ziv_server.py` reads
`ZIV_PORT` with a default of `8787`, not `$PORT`. That is a concrete hosting mismatch
to fix in the deploy wrapper or env mapping, not to paper over with a localhost assumption.

## 3) Env for the keyless demo

### Set nothing extra for the default keyless link
For the judge-facing keyless demo:
- `NEBIUS_API_KEY` — leave unset.
- `ZIV_RELAY_TOKEN` — leave unset, so auth is off.
- `ZIV_TEXT_MODEL` — leave at default or unset; it only matters if a key is present.
- `NEBIUS_BASE_URL` — leave at default.
- `ZIV_OMNI_MODEL` — leave unset.

### What that yields
- Scheduled intents fire verbatim, labelled `text_echo`.
- `POST /inject/audio` answers 503.
- The client page, timing, health, schedule, inbox, and message routes work.
- The whole turn shape, queue/429/redial, and always-on reminder beat still demo.

### The one env mapping a Render deploy still needs
- `ZIV_PORT` must match the Render-assigned `$PORT`, or the service will not accept public traffic.
- If Render supplies `$PORT`, the deploy wrapper should pass it through as `ZIV_PORT`.

## 4) How to reach the demo from a phone/judge

The URL shape is:

```
https://<render-service-url>/ziv_client/index.html
```

and the relay origins are:

```
https://<render-service-url>/api/ziv/*
wss://<render-service-url>/ws
```

The client page uses relative URLs for `/ws` and `/api/ziv/*`, so the same deployed origin
should serve both the page and the relay. That is the real reason this can be a single hosted
process instead of a static page plus a separate API host.

If the Render service is served over HTTPS, the page origin is TLS and the WS scheme is `wss`.
Verify the deployed origin does not break WS negotiation.

## 5) Verification checklist for the public link

Run these against the deployed URL, not against localhost.

### 5.1 Health
```
GET https://<render-service-url>/api/ziv/health
```
Expect: `200`. Check that the payload includes counts/telemetry/wiring only:
queue depth vs cap, rejection count/rate, schedule depth vs cap and corrupt flag,
turn telemetry, and the model/auth wiring flags.

Do NOT accept the link as judge-ready if the health payload includes any message text,
reminder text, or inbox content. Re-verify that claim on the deployed instance.

### 5.2 Page served
```
GET https://<render-service-url>/ziv_client/index.html
```
Expect: `200` and the real client page content, not a proxy error or a different page.

### 5.3 Keyless demo path
```
POST https://<render-service-url>/api/ziv/message
{"text": "taxi arrived"}
```
Expect: accepted or queued, or `inbox:stored` if no device is attached — not a 500 and not
a static-site error.

```
POST https://<render-service-url>/api/ziv/schedule
{"fire_at": <future epoch>, "text": "pills"}
```
Expect:
```
{"scheduled": true, "id": ..., "fire_at": ..., "fire_at_iso": ..., ...}
```

### 5.4 WebSocket reminder beat over the public origin
Schedule a reminder a short time in the future, then attach a WS client to:

```
wss://<render-service-url>/ws
```

Expect the reminder to arrive as a self-naming turn:
- prefix mark line,
- cue,
- processing ticks,
- content cells,
- close,
- queue release.

If the WS path works over the public origin, the link is the real full demo, not just a
static page.

### 5.5 Cold-start caveat
If this is a Render free web service:
- expect the worker to spin down after about 15 minutes without inbound traffic,
- expect a slow wake on the first request or WS connect after idle,
- and state that caveat plainly with the link.

If instant-first-open matters, that is an always-on/paid line, not a workaround on the
free tier.

## 6) What not to claim until verified

Do not claim any of these until the deployed URL passes the checklist above:
- “the hosted link works,”
- “the page is reachable,”
- “the WebSocket beat works over the public URL,”
- “the health payload is safe.”

A successful deploy receipt is not the same as a working demo link.

## 7) What is still missing if this environment cannot deploy

If this machine cannot actually provision/deploy the Render service, then this handoff is
the deliverable: a concrete host-specific build + run + verify checklist, the exact env to
set and leave unset for the keyless demo, the exact URL shape to hand to a phone/judge, and
the verification steps that prove it is the real full demo.

If you want me to keep going, the next step is either:
- use the Deploy surface available in this environment to create the Render service and
  verify the public URL end-to-end, or
- run the deploy yourself from this handoff and let me verify the public link once it exists.

Either way, do not hand out a localhost-only link and call it hosted.
