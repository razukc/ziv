# SkillForge handover — 2026-09-17

This repository's Ziv (haptic wrist) and SkillForge (robot pipeline composer)
tracks were built in one checkout and are now separated. **SkillForge moved to
its own repository; this repo is Ziv-only from here on.**

- **SkillForge repo:** `../SkillForge` — a sibling checkout, initialized as a
  fresh git repo, tagged `handover-2026-09-17` on the verified snapshot.
- **This repo:** Ziv only. Nothing SkillForge remains in its working area or
  CI; the changelog below `pre-v0.1.46` still tells the shared history
  (this repo's milestone tags `pre-v0.1.0`–`pre-v0.1.46` cover both tracks).

---

## What the SkillForge agent receives

The copy at `../SkillForge` contains the full SkillForge surface, taken from
the verified snapshot (SkillForge suite **86 passed** immediately before the
copy):

```
SkillForge/
├── agent/
│   ├── server.py               # FastAPI app: compose, export, validate, share links
│   ├── reasoning_agent.py      # Nemotron decompose/explain/improve (Token Factory)
│   ├── relay_compose.py        # compose scaffolding split out of ports.py (pre-v0.1.44)
│   ├── ports.py                # common infra: retry/SSE/TelemetryRing/mock switch
│   ├── skill_registry.py · robot_registry.py · registry_tools.py
│   ├── ros2_package.py · validation.py   # export + validate
│   ├── pipeline_store.py       # Upstash Redis / local JSON persistence
│   ├── live_check.py · live_share_link_check.py   # live verification harness
│   ├── e2e_helpers.py          # shared browser-e2e helpers
│   ├── tests/                  # 16 hermetic suite files (86 tests)
│   ├── .env / .env.example     # NEBIUS_API_KEY, UPSTASH_REDIS_* (kept local-only)
│   └── requirements.txt        # includes upstash-redis (SkillForge-only dep)
├── frontend/                   # Next.js 15 app (source only — no node_modules)
├── docs/                       # CAPABILITIES, MIMICLAW_PIPIN, screenshot, …
├── CONTRIBUTING.md             # the pre-handover conventions (kept for reference)
├── SECURITY.md                 # moved with the project (its reporting channel)
├── DEVPOST.md · README.md · LICENSE
├── .gitignore
└── requirements-dev.txt        # agent/ dev deps (pytest, playwright for e2e)
```

Not copied (with reasons):

- `agent/venv/` — create a fresh venv (`pip install -r agent/requirements.txt`);
  it installs cleanly from the manifest.
- `frontend/node_modules/` — run `npm ci` from the lockfile.
- Ziv-only files — they never belonged to SkillForge (`ziv_*.py`,
  `tests_ziv/`, `firmware/`, `tools/`, most of `docs/`).

## How to bring SkillForge up (in `../SkillForge`)

```bash
cd SkillForge/agent
python -m venv venv && venv/Scripts/activate     # Windows Git-Bash form
pip install -r requirements.txt
python server.py                                  # backend at :8000

cd ../frontend
npm ci
npm run dev                                       # frontend at :3000 (proxies to :8000)
```

Verify: `cd agent && python -m pytest -q` → **86 passed**. The suite is
hermetic (LLM faked, store forced local) and needs no keys. The old repo's
conventions apply: conventional commits, `pre-v0.1.x` checkpoint tags,
CHANGELOG-per-milestone — the receiving agent may rebrand, but the rhythm
is documented in the copy's historical `CONTRIBUTING.md`.

## What changed at the seam (pre-v0.1.44 separation, still current)

- `agent/ports.py` is common infrastructure only: retry with backoff
  (`sleep_with_backoff`), SSE helpers, `TelemetryRing`, the mock-mode switch.
- `agent/relay_compose.py` owns the compose scaffolding: `RelayResult`,
  `RelayConfig`, `RelayAdapter`, `relay_run_turn`.
- The two tracks share no conftest, no fixtures, and no imports in either
  direction — contract tests in the historical suites asserted that
  isolation and it is preserved by the split.

## What the Ziv repo keeps (this checkout)

Everything else: the relay seam (`ziv_relay.py` — `MessageGate`,
`TurnTimeline`, lifecycle constants, and now `TelemetryRing`, folded in from
ports.py), the dev-band server + PWA client, `ziv_store.py`, the
`haptic_out` sequencer, the QEMU ladder (`firmware/app/ziv_qemu/`,
`tools/qemu_timeline.py`), the timing spec's generator + drift guard
(`tools/haptic_timing.py`, 7 generated consumers), and the demo-chain single
source (`tools/build_ziv_demo.py`). The Ziv test suite lives in
`agent/tests/` (formerly `agent/tests_ziv/`).

## Why separate now

The two tracks shared a repo but never a runtime: no shared process, no
shared deploy, no cross-imports since pre-v0.1.44. Keeping them together
cost more each week — two CI suites in one job, a changelog where every
milestone had to say which track it served, and a handover (this one) that
would have dragged a haptic-wrist repo along just to move a robot-pipeline
composer. Separate checkouts let each agent work at its own cadence without
the other's gates in the way.
