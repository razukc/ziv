# Hosted Render build — agent/ziv_server.py (keyless, auth off)

This is the host-specific checklist for the managed Python Web Service target we leaned toward.
It is not a deploy receipt. It is the thing to run or hand to a deploy step.

## 0) The honest blocker before claiming a hosted build

The repo has:
- no deploy manifest,
- no package entrypoint,
- and one proven start command: `python agent/ziv_server.py` from the repo root.

That command works locally because `agent/ziv_server.py` does runtime `sys.path`/relative-path
work to import `tools/haptic_timing_gen.py` and serve `agent/ziv_client/index.html`.

A hosted build is only “ready” once we confirm the deployed working directory makes that same
import/serving path true. If the host runs from a different root, or copies only a subdirectory,
the app can fail with missing modules or a missing client page even though the deps installed.

So the real build step is not “install deps and start uvicorn.” It is:
- install deps,
- arrange the working directory / path so `agent/` and `tools/` are importable and reachable,
- map the host-assigned port into `ZIV_PORT`,
- start the app.

## 1) What to install

From the repo root:

```
pip install -r agent/requirements.txt
```

That file is the real dependency list for the relay. There is no separate frontend build step.

## 2) What to serve

The full demo is one process. The app serves:
- the page at `/ziv_client/index.html`,
- the API and WS routes under `/api/ziv/*` and `/ws`.

No separate static host is required for the demo.

## 3) Start command shape

If the deployed environment can run the repo root layout:
```
pip install -r agent/requirements.txt
python agent/ziv_server.py
```

If the host assigns a port through an env var such as `$PORT`, that port must be passed into
`ZIV_PORT`, because `agent/ziv_server.py` currently reads `ZIV_PORT`, not `$PORT`.

If the host root cannot make `agent/ziv_server.py` importable as-is, use a thin wrapper that
restores the repo’s import layout before starting the real file. Keep that wrapper minimal and
in service of the existing entrypoint, not a rewrite of the app.

## 4) Env to set for the keyless demo

Set:
- `ZIV_PORT` to the host port if the host assigns one.

Leave unset:
- `NEBIUS_API_KEY`
- `ZIV_RELAY_TOKEN`
- `ZIV_TEXT_MODEL` unless you are testing the live path locally only
- `NEBIUS_BASE_URL`
- `ZIV_OMNI_MODEL`

That keeps the deployed demo on the keyless `text_echo` path, with auth off.

## 5) URL shape to hand to a phone/judge

```
https://<service-url>/ziv_client/index.html
```

Origins:
```
https://<service-url>/api/ziv/*
wss://<service-url>/ws
```

Do not hand out a localhost URL and call it hosted.

## 6) Verification

Run these against the deployed URL:

1. `GET /api/ziv/health` → `200`, and the payload only exposes counts/telemetry/wiring.
2. `GET /ziv_client/index.html` → `200` and the real client page.
3. `POST /api/ziv/message` with a text body → accepted/queued/inbox-stored, not a build error.
4. `POST /api/ziv/schedule` with a future `fire_at` → `{"scheduled":true,...}`.
5. A WS client on `wss://<service-url>/ws` receives a scheduled reminder as a full turn
   over the public origin.

If step 5 fails, the link is not yet the full hosted demo.

## 7) Caveat to state with the link

If this is a Render free web service:
- it can spin down after idle,
- the first open or WS connect after idle can be slow,
- and that caveat should be stated plainly with the link.

If instant-first-open matters, that is an always-on/paid line.
