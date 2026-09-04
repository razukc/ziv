# Roadmap

Living list of what's next. Status meanings:

- `[ ]` — candidate (not started)
- `[~]` — in progress
- `[x]` — shipped (moved here from the list so history stays visible)

Shipped work is logged with dates in [CHANGELOG.md](../CHANGELOG.md) and
checkpoint tags (`pre-v0.1.x`). Promote items to `[~]` only when you're
actively working them.

## Before 0.1.0 (pre-release polish)

- [x] **Iterable pipelines** — persisted history + reopen-in-editor
      (`pre-v0.1.1`, 2026-09-03)
- [ ] **Product name decision** — SkillForge is a working title; pick the
      public name and do the repo-wide rename before the public repo / 0.1.0
- [x] **Fork-as-variation** — reword the task / pick a robot and compose a
      new pipeline seeded from the current one (`pre-v0.1.2`, 2026-09-03)
- [x] **Resilient live composes** — all LLM round-trips retry up to 3× with
      backoff, so a flaky/truncated model response can't 500 a live compose
      (`pre-v0.1.3`, 2026-09-04)
- [x] **Visible auto-retry** — the compose UI shows a small
      "auto-retried once/N times" note when a live compose healed after a
      transient blip (`pre-v0.1.4`, 2026-09-04)
- [x] **Session auto-retry awareness** — retries are tallied per tab session
      and the UI suggests mock mode or a simpler task once the model has
      blipped 3+ times (`pre-v0.1.8`, 2026-09-04)
- [x] **Live compose latency visibility** — the done event carries wall time
      + retries, the UI ticks a live elapsed while composing, and results
      show "compose took Xs (auto-retried Nx)" (`pre-v0.1.9`, 2026-09-04)
- [x] **Retry counts on request/response endpoints** — compose, compose/silent,
      and improve carry `retries` so non-stream API clients and live_check
      reports see healed LLM blips too (`pre-v0.1.10`, 2026-09-04)
- [x] **Per-phase compose timing** — the done event breaks the run into
      decompose / explain / logs wall times and the results view shows the
      breakdown under the total (`pre-v0.1.11`, 2026-09-04)
- [x] **Slow-compose warning** — a live compose that beats the session's
      moving median baseline by 2x+ gets a warn note suggesting a retry or
      a simpler task, mirroring the frequent-blip hint (`pre-v0.1.12`,
      2026-09-04)
- [x] **Compose telemetry on /api/health** — rolling latency + healed-retry
      stats (samples, avg/p95, tail) from recent composes for ops
      (`pre-v0.1.13`, 2026-09-04)
- [x] **Compose time on history cards** — live entries persist their compose
      stats, cards show "⏱ 11s · retried 1×", and reopening restores the
      timing disclosure (`pre-v0.1.14`, 2026-09-04)
- [x] **Per-robot capability gate** — skills declare the anatomy they need
      (arm/legs/cameras); every compose is validated against the robot's
      profile and incompatible plans are rejected with a clear error
      (`pre-v0.1.5`, 2026-09-04)
- [x] **Quadruped-class skills** — legged manipulation + terrain adaptation
      so Go2-style robots get plans that interact with objects and handle
      rough ground (`pre-v0.1.6`, 2026-09-04)
- [x] **Visible adaptation reasoning** — a per-step card explains why each
      variation step was kept/reworded/added and why each dropped skill
      went (robot anatomy or the reworded task), LLM-free from the seed
      (`pre-v0.1.7`, 2026-09-04)
- [ ] **Resume failed live composes** — keep partial thinking/logs on screen
      after a fully failed or timed-out live call and offer a one-click retry
      that reuses them instead of wiping state (server-side auto-retry
      shipped `pre-v0.1.3` and a session blip hint `pre-v0.1.8`; this item
      is the remaining UI state gap)
- [ ] **Stale-card awareness in history** — mark live cards whose Redis copy
      expired, refresh all live cards in one batched request on load

## Demo / hackathon stretch (from README "What's Next")

- [ ] **Isaac Sim integration** — execute pipelines directly in simulation
- [ ] **Expanded skill catalog** — add Isaac Lab, cuRobo, and more NVIDIA tools
- [ ] **Cost optimization mode** — agent suggests cheaper alternatives
- [ ] **Multi-robot support** — compose pipelines for robot swarms

## Shipped earlier

- [x] **Pipeline editor** — reorder/swap/remove steps, LLM-free re-export
      (baseline, `pre-v0.1.0`)
- [x] **Pipeline versioning core** — share links, persisted history,
      side-by-side compare (baseline + `pre-v0.1.1`)

## How items get here

Pull from the README "What's Next", `DEVPOST.md`, or ideas that come up in
iteration. Each item should be one sentence naming the outcome; the agent
implementing it is free to choose the approach. When an item ships, add a
CHANGELOG entry, tick it here, and tag a milestone if it's substantive.
