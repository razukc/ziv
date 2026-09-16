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
- [x] **Simulation dry-run panel** — replay any composed pipeline
      step-by-step with real pacing and seeded pass/fail against skill
      metadata (deterministic structural checks + seeded execution risk,
      preflight scan, pause/replay/new-scenario). the honest scaffold that
      a real Isaac Sim execution can later plug into
      (`pre-v0.1.15`, 2026-09-04)
- [x] **Dry-run verdicts on history cards** — completed runs persist their
      seed/elapsed/verdicts onto the history entry, cards show a pass/fail
      badge, and reopening renders the stored result instantly (stale
      records auto-invalidate when the plan changed)
      (`pre-v0.1.16`, 2026-09-04)
- [x] **Registry tool use in compose** — the decompose agent queries the
      skill/robot registries as structured tools (list_skills, get_skill,
      get_robot, check_capability) so plans are grounded in registry data
      rather than the catalog text in the prompt; lookups surface in the
      reasoning stream and are counted on every compose response, with a
      prompt-only degradation path for providers that reject tools
      (`pre-v0.1.17`, 2026-09-04)
- [x] **Measured tool policy** — live A/B (12 seeded crossings) showed tools
      add no gate benefit on seeded variations (0/12 either way) for ~3x
      latency, so seeded runs now default prompt-only while fresh
      decomposes keep the tools; rules forbid re-reading the catalog
      (parallel tool calls aren't supported by the model), cutting a fresh
      compose from 21 to 2 tool calls with the same result
      (`pre-v0.1.18`, 2026-09-04)
- [x] **Grounding disclosure + opt-out** — the compose-timing strip reports
      how grounded each live compose was (registry lookups vs
      prompt-based), persisted on history entries; the live compose box has
      a grounding toggle that sends `tools_enabled: false` for prompt-only
      composes (~30s vs ~60-100s)
      (`pre-v0.1.19`, 2026-09-04)
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

## Personal AI (Ziv)

- [x] **Queue-don't-interrupt relay behavior** — incoming messages during haptic
      playback get their attention cue only and queue their content until the
      wearer closes the event (plan §4 invariant 4, from early-years deafblind
      practice); `MessageGate` in `agent/ziv_relay.py`, proven in the hermetic
      e2e suite (`pre-v0.1.34`, 2026-09-12)
- [x] **Executable invariants (TurnTimeline)** — the turn state machine (kind
      cue → processing ticks → playing → end-of-message → gate release),
      wired to the queue gate; out-of-order transitions raise in the seam,
      and the e2e suite proves the whole wearer-visible journey
      (`pre-v0.1.39`, 2026-09-13)
- [~] **Dev-band relay v0** — the phone stands in for the wrist until boards
      ship: `agent/ziv_server.py` (WS transport with optional token auth,
      message turn pump through the real `MessageGate` + `TurnTimeline`,
      `/api/ziv/timing` serving the generated module) + the PWA client
      (`agent/ziv_client/index.html`, Vibration API, zero hand-copied timing)
      + `/inject/audio` as the Omni spike's seam (`pre-v0.1.41`); the spike's
      mic half is real now — the PWA records a MediaRecorder clip and the
      relay transcribes it with Nemotron-3-Nano-Omni on Nebius Token Factory
      (`NEBIUS_API_KEY`-guarded: 503 without a key, 502 on provider errors;
      the `simulate` stub keeps the keyless hermetic demo path)
      (`pre-v0.1.43`)
- [~] **WS relay v1 (dev-band form)** — per-wearer memory files
      (`agent/ziv_store.py`: atomic JSON, corrupt-file recovery surfaced in
      health) and a persistent, capped message inbox — a message that arrives
      with no band attached is stored, not dropped, and delivered as a full
      event on the next attach (mark-after-play: redelivery, never loss);
      the wearer's playback pace is a stored preference, clamped into the
      spec envelope. The full `ZivRelayAdapter` run_turn (device-side text
      frames, Token Factory round-trip) stays open (plan §7 week 3)
      (`pre-v0.1.42`)
- [~] **QEMU boot app (rung 1)** — an ESP-IDF app skeleton that boots the real
      `haptic_out` binary in Espressif's QEMU fork with the bench mock bus as
      the haptic backend, prints `HAP` timelines from the sequencer's event
      stream, and diffs bench vs QEMU for equivalence
      ([QEMU_SIMULATION_LADDER.md](QEMU_SIMULATION_LADDER.md));
      host-portable core shipped and proven (49-check bench fixture,
      `python firmware/app/ziv_qemu/run_ziv_tests.py`) — QEMU boot + rung-2
      differ pending an IDF/QEMU install

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
