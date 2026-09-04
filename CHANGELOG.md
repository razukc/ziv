# Changelog

All notable changes to SkillForge are tracked here, one entry per milestone
tag (see [CONTRIBUTING.md](CONTRIBUTING.md)). Format follows
[Keep a Changelog](https://keepachangelog.com/); the project is in the
pre-release phase, so milestones are tagged `pre-v0.1.x` until the public
`0.1.0`.

## [pre-v0.1.3] — 2026-09-04 — resilient live composes

Fix commit: `3a49325` (fix: retry LLM round-trips so flaky live composes
can't hard-fail).

### Fixed
- **Bounded retry on every LLM round-trip** — a shared retry helper now runs
  decompose, seeded-variation, and explain prompts up to 3 attempts with
  backoff, rejecting empty/`null` content and retrying malformed (incl.
  fenced) JSON. Discovered live: the seeded-variation path 500'd with
  `'NoneType' object has no attribute 'strip'` when Nemotron returned empty
  content; with no retry, one flaky response was a hard, cryptic failure.
  A meaningful error is raised only after all attempts fail.
- **Tests** — 6 new hermetic unit tests with a stubbed OpenAI client (no
  API key or network): retry after empty responses and truncated/fenced
  JSON, give-up after max attempts, seed preserved across retries, and
  explain retries on empty content. Suite counts: 51 hermetic,
  4 browser E2E.

## [pre-v0.1.2] — 2026-09-03 — seeded variations

Feature commit: `cede1d9` (feat: compose seeded pipeline variations).

### Added
- **Create variation flow** — a "🧬 create variation" action on the pipeline
  header opens a composer prefilled with the displayed plan's task and robot;
  rewording the task or switching robots composes a NEW pipeline. Each
  variation lands as its own history entry; the original stays available.
- **Seeded compose (backend)** — optional `seed_pipeline` field on
  `/api/compose`, `/api/compose/silent`, and `/api/compose/stream`; the agent
  prompt now produces a VARIATION, keeping steps/skills that still apply and
  adapting or dropping the rest for the new task/robot.
- **Tests** — 3 hermetic tests for seed propagation (compose + stream),
  plus a browser E2E for the mock variation flow. Suite counts: 45 hermetic,
  4 browser E2E.

## [pre-v0.1.1] — 2026-09-03 — iterable pipelines

Feature commit: `cb3dbc8` (Make composed pipelines iterable).

### Added
- **Persisted pipeline history** — composed pipelines survive reloads:
  localStorage snapshots for mock pipelines (the only record of them), Redis
  pipeline ids for live ones; entries deduped by id and capped at 30
  (`sf-history-v1`).
- **"↪ open in editor" on history cards** — restores the full results view
  (task, robot, summary, timeline, export) and the `#p=` URL hash. Live
  entries refresh from the store on reopen, falling back to the stored
  snapshot when the 7-day TTL has expired.
- **Robust LLM-free re-export after reopen** — exports treat the inline
  pipeline as authoritative when no valid server id exists, so stale ids
  can't make the backend re-export the wrong original.
- **History provenance badges** on cards (`live · p…` vs `mock · local`).
- Third browser E2E test: persist → reopen → edit → re-export.

### Changed
- `HistoryItem` gains `kind: "mock" | "live"` and an optional `pipelineId`.
- README: history feature bullet and E2E test count updated (3 E2E tests).

## [pre-v0.1.0] — 2026-09-03 — initial baseline

Root commit: `4da586d`. The first committed state of the whole project.

### Added
- **Compose** — plain-English task → costed NVIDIA skill pipeline, via mock
  mode (no backend) or the live Nebius LLM API (SSE stream: thinking →
  pipeline → explanation), with a mock/live switch in the compose box.
- **Share links** — pipelines stored by id (Upstash Redis when configured,
  local file fallback); `/#p=<id>` restores any pipeline client-side.
  Cross-instance share-link E2E + rate limiting on link resolution.
- **ROS2 export + validation** — buildable packages (package.xml, CMakeLists,
  launch files) exported server-side or client-side, validated with
  structural checks (100/100 scorer).
- **Human-editable pipeline view** — reorder/swap/remove steps and re-export
  LLM-free.
- **Plain-words layer** — "what this plan does" summary card + glossary
  tooltips so results read clearly to non-robotics users; layered fallback
  rewrites arbitrary step names.
- **Design system** — token-based dark/light themes (OS-following default +
  manual toggle), WCAG-contrast-audited light palette.
- **Ops surface** — `/api/health` reports store backend (redis/memory), entry
  count, Redis connectivity; `live_check.py` CLI consolidates the live
  verification scripts (share-links / journey / edit).
- **Tests** — 42 hermetic pytest tests + 2 browser E2E tests at this tag.

### Notes
- Working title "SkillForge" — rename decision deferred until the public
  repo / 0.1.0 (tracked in `docs/ROADMAP.md`).
