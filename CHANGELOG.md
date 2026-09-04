# Changelog

All notable changes to SkillForge are tracked here, one entry per milestone
tag (see [CONTRIBUTING.md](CONTRIBUTING.md)). Format follows
[Keep a Changelog](https://keepachangelog.com/); the project is in the
pre-release phase, so milestones are tagged `pre-v0.1.x` until the public
`0.1.0`.

## [pre-v0.1.9] — 2026-09-04 — live compose latency visibility

Feature commit: `4f27a0f` (show compose wall time so slow LLM calls read as
slow, not stuck).

### Added
- **Compose wall time on the wire** — the SSE compose stream times the whole
  run (LLM round-trips + retry backoff + streaming) and the `done` event now
  carries `seconds` and `retries`, so API clients and the UI both learn how
  long a compose actually took.
- **Ticking elapsed while processing** — a live compose shows "⏱ compose
  running — Ns elapsed" under the task bar, ticking each second, so a slow
  LLM round-trip reads as slow instead of stuck (mock composes keep their
  animated progress and show nothing).
- **"compose took Xs" results line** — when the compose completes, the line
  becomes "⚡ compose took 23s", or "↻ compose took 23s (auto-retried 1×,
  healed on its own)" in the warn palette when round-trips had to be
  retried — folding the pre-v0.1.4 standalone auto-retry note into one
  latency + retry disclosure. Clean live composes and mock composes show
  nothing extra.
- **Tests** — the clean and retried compose-stream tests now assert the
  `done` event reports `seconds > 0` and the correct `retries` (0 clean / 1
  after a healed retry). Suite counts unchanged: 70 hermetic, 5 browser E2E.

## [pre-v0.1.8] — 2026-09-04 — session auto-retry awareness

Feature commit: `7a888d3` (warn when live composes auto-retry often in a
session).

### Added
- **Session auto-retry tally** — every healed retry a live compose reports is
  accumulated for the tab session (`sf-session-retries` in sessionStorage, so
  the count survives reloads), instead of each compose being treated as an
  isolated event.
- **Frequent-blip hint** — once the model has auto-retried 3+ times in the
  session, the UI shows a nudge — "model auto-retried N times this session —
  if it keeps blipping, try mock mode or a simpler task" — beside the
  compose-mode switch in the input view and in the processing/results view
  (only when that section is on screen). Switching to mock mode clears the
  tally, since that is the suggestion being taken.
- **Tests** — fifth browser E2E: seeds the sessionStorage tally, reloads in
  the same tab, and asserts the hint stays hidden in mock mode, appears on
  switching to live, and clears (with the storage) when mock is chosen
  again — no compose, backend, or credits needed. Suite counts:
  70 hermetic, 5 browser E2E.

## [pre-v0.1.7] — 2026-09-04 — visible adaptation reasoning

Feature commit: `a1c6339` (explain per-step adaptation on seeded variation
results).

### Added
- **"🧬 adaptation — how this plan changed" card** — whenever a variation
  lands (fresh compose, reopen from history, or share-link restore), the
  results view now shows why each step of the new plan differs from the
  seed: variation steps are tagged **still applies** (carried over
  unchanged), **kept + reworded** (adapted for the new task), or **new**
  (added for the new task/robot), matched to the original by skill id; and
  every original step that didn't survive is listed with the reason — the
  new robot's anatomy ("Unitree R1 has no arm, and policy-training-gr00t
  needs it to work") or the reworded task dropping it.
- **Deterministic, LLM-free diff** — `diffAdaptation` compares the seed and
  the result purely client-side (no extra credits), mirroring the backend
  robot/skill anatomy tables so drops are explained even offline in mock
  mode. The report is persisted with the history entry, so reopening a
  variation later shows the notes again.
- **Tests** — the variation browser E2E now switches robot G1 → R1 (the
  armless compact) and asserts the card explains the arm-skill drops with
  the anatomy reason, marks the locomotion step as new, and words the kept
  steps as still applying. Suite counts: 70 hermetic, 4 browser E2E.

## [pre-v0.1.6] — 2026-09-04 — quadruped-class skills

Feature commit: `9cc9303` (add quadruped-class skills).

### Added
- **`legged-manipulation`** (Isaac Lab / Isaac Sim, ~$1.20) — push, carry,
  and reposition objects with the body and legs; no arm required
  (requires legs + cameras).
- **`terrain-adaptation`** (SONIC / Isaac Lab, ~$1.00) — gaits and recovery
  that adapt to rough, slippery, or uneven ground (requires legs).
- Both skills carry anatomy tags, so they pass the capability gate for
  Go2-class and other legs-only robots (which previously had no way to
  interact with objects or plan for rough ground), and the catalog grows to
  11 skills — surfaced automatically in the skill browser and the LLM
  prompt. `get_skills_for_task_type` mappings updated to match.
- **Plain-words coverage** — everyday sentences for both ids, plus keyword
  rules ordered so body-level "push / carry / legged" phrasing beats the
  generic arm-handling rule and terrain/rough-slip phrasing beats the
  locomotion catch-all (with a word-boundary so "through" can't trigger
  "rough").
- **Tests** — catalog-list test now asserts 11 skills incl. both new ids;
  gate tests prove the new skills are legal for go2/r1 and that legged
  manipulation still needs legs. Suite counts: 70 hermetic, 4 browser E2E.

## [pre-v0.1.5] — 2026-09-04 — robot capability gate

Feature commit: `3253805` (gate every compose against the robot's anatomy).

### Added
- **Skills declare the anatomy they need** — every catalog skill now carries
  `requires` (arm / legs / cameras); scene creation, data synthesis,
  validation, and packaging work for any body, while GR00T and motion
  planning require an arm, SONIC requires legs, and perception / world
  models require cameras.
- **Robot registry** — `robot_registry.py` profiles the robots the API
  accepts (`unitree-g1` bipedal humanoid, `unitree-r1` compact legged,
  `1x-neo` humanoid, `unitree-go2` quadruped) with their anatomy. Robot
  strings are no longer free-form.
- **Compose gate** — every LLM-composed pipeline (fresh or a seeded
  variation) is validated against the *requested* robot before it is
  stored: a plan that asks an armless robot to train arm skills is
  rejected with a clear 422 naming the offending steps, instead of the
  model's output being trusted. Unregistered robot slugs fail before any
  LLM call. The SSE stream surfaces rejections as an error event; nothing
  incompatible is ever stored.
- **Tests** — 12 new hermetic tests: registry consistency, mock-pipeline
  compatibility, arm/legs/camera requirement logic, unknown-robot
  messaging, and API-level 422s on compose/silent plus the SSE error
  event. Suite counts: 68 hermetic, 4 browser E2E.

### Fixed
- `test_compose.py`'s stream-variation test targeted `unitree-r1` with an
  arm-skill seed — now correctly a humanoid (`1x-neo`) under the gate.

## [pre-v0.1.4] — 2026-09-04 — visible auto-retry

Feature commit: `b0b7e5a` (surface auto-retried live composes in the UI).

### Added
- **Auto-retry is now visible** — when a live compose has to retry a
  transient LLM blip, the UI shows a small note under the task bar
  ("↻ model hiccup — auto-retried once / N times, compose healed on its
own"), so a slow-but-recovered call is no longer indistinguishable from
  a hang. Mock composes and clean live composes show nothing.
- **Agent reports healed retries** — the LLM methods accept an optional
  `on_retry(attempt, error)` callback invoked after each failed attempt
  that is retried; the SSE compose stream counts these across decompose
  and explanation and emits a `notice` event before `done`.
- **Tests** — 5 new hermetic tests: on_retry fires per healed attempt with
  1-based numbering, stays silent on clean calls and on calls that fail
  for good, and the stream emits a `notice` event (retries=1) after a
  stubbed failure while clean streams carry none. Suite counts:
  56 hermetic, 4 browser E2E.

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
