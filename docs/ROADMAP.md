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
- [ ] **Fork-as-variation** — from a reopened pipeline, reword the task or
      pick a different robot and compose a new pipeline seeded with the
      original's context
- [ ] **Resume failed live composes** — keep partial thinking/logs on screen
      after a failed or timed-out live call and offer a one-click retry that
      reuses them instead of wiping state
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
