# Ziv — a haptic wrist companion

**Messages you can feel.** A wristband that taps out incoming messages in
haptic braille so a deafblind wearer can stay connected without a screen or
sound.

> The product plan lives in
> [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) — invariants,
> phases, hardware BOM. SkillForge (the earlier project in this repo) moved to
> its own repository: [docs/HANDOVER_SKILLFORGE.md](docs/HANDOVER_SKILLFORGE.md).

---

## What Ziv does

- **Haptic braille turns** — every message plays as a fixed journey the wearer
  can learn: kind cue → processing ticks → braille cells → end-of-message
  close, timed by the generated feel spec
- **Queue, don't interrupt** — a message arriving during playback gets its
  attention cue only and queues until the current event closes (plan §4
  invariant 4, from early-years deafblind practice); a full queue gets a
  loud, sender-visible refusal (HTTP 429 + `message:rejected`)
- **The close that frees the wrist is marked on the wire** (`free: true`) —
  the client's auto-redial fires on that frame, never on a timing guess
- **Durable wearer state** — memory files + a persistent, capped inbox
  (`agent/ziv_store.py`): a message arriving with no band attached is stored,
  not dropped, and delivered as a full event on the next attach
  (mark-after-play: redelivery, never loss)
- **Always-on is the relay, not the device** — the relay is the 24/7 presence
  (heartbeat + scheduled jobs); the wristband sleeps between events and wakes
  on button/chord/mic/WiFi activity. The phone PWA stands in for the wrist
  until boards ship — it renders the relay's turns through the Vibration API,
  transcribes it with Nemotron-3-Nano-Omni on Nebius Token Factory
- **Prove it before hardware** — the QEMU simulation ladder: a host-portable
  bench (49-check C fixture), a boot app for Espressif's QEMU fork, and a
  differ that pins the boot log to the same derived fixture the app plays

---

## Repo layout

| Path | What it is |
|------|------------|
| `agent/ziv_relay.py` | The relay seam: `MessageGate`, `TurnTimeline`, lifecycle constants, `TelemetryRing` |
| `agent/ziv_server.py` | The dev-band relay server — WS transport (optional token auth), HTTP API, serves the PWA |
| `agent/ziv_client/index.html` | The PWA client (queue badge, refusal note, auto-redial) |
| `agent/ziv_store.py` | Per-wearer memory files + inbox (atomic JSON, corrupt-file recovery) |
| `agent/requirements.txt` · `agent/.env.example` | Python deps + env vars |
| `firmware/haptic_out/` | The haptic sequencer — the C core that renders messages into actuator events |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app + host demo (ladder rungs 1–2) |
| `tools/haptic_timing.py` | The timing spec's generator + drift guard (7 generated consumers) |
| `tools/build_ziv_demo.py` | The demo-chain single source — one `DEMO_STAGES` generates app, fixture, and docs |
| `tools/qemu_timeline.py` | The rung-2 differ (bench/boot HAP logs vs the derived fixture) |
| `docs/` | Plan, timing spec, QEMU ladder, hardware bring-up + shopping |

---

## Quick start (dev-band relay)

Prerequisites: Python 3.10+. No key needed for the hermetic demo path.

```bash
cd agent
cp .env.example .env        # optional: NEBIUS_API_KEY enables the real Omni path
python -m venv venv
source venv/bin/activate    # venv\Scripts\activate on Windows
pip install -r requirements.txt
python ziv_server.py
```

Open the printed URL (default `http://127.0.0.1:8787`) on your phone — the PWA
stands in for the wrist. Without `NEBIUS_API_KEY` the Omni path runs the
keyless stub: the whole turn/gate/queue journey is real, only transcription is
stubbed.

---

## Tests

```bash
cd agent
python -m pytest -q          # hermetic suite — browser e2e deselected
python -m pytest -m e2e      # Playwright e2e (real server + real browser)
```

The hermetic suite covers the seam (gate, timeline, threaded concurrency),
the server endpoints, the store, the timing drift guard, and the demo-chain
generation. The e2e tier includes the redial test: a real `MessageGate` filled
to the cap behind a live turn, a 429, and the client re-sending by itself when
the freeing close lands on the wire.

Firmware-side checks (host-portable, no IDF needed):

```bash
python firmware/app/ziv_qemu/run_ziv_tests.py    # 49-check C bench + boot check
```

---

## The timing spec is generated — never hand-edit a consumer

`docs/haptic-timing.json` is the single source of truth for feel timing;
seven consumers are generated from it (firmware header, feel-tool JS, the
ladder doc's demo table, …). The drift guard fails on any hand edit to a
generated block:

```bash
python tools/haptic_timing.py          # verify (also run by the pre-commit hook)
python tools/haptic_timing.py --write  # regenerate / heal the consumers
```

One deliberate asymmetry, guarded by the drift guard: the feel-tool's spell
box caps at 12 letters (page affordance) while the firmware accepts 16
(`HAPTIC_OUT_MAX_WORD_LEN`, runtime ceiling). Do not unify them.

---

## Security

Ziv stores the wearer's messages and memory files locally in
`agent/ziv_data/` (gitignored — user data, never repo state). The relay
server binds to loopback by default; the WS transport accepts an optional
shared token (`ZIV_RELAY_TOKEN`). This is a single-developer project — no
separate disclosure channel yet; contact the maintainer directly.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
