# Changelog

All notable changes to SkillForge are tracked here, one entry per milestone
tag (see [CONTRIBUTING.md](CONTRIBUTING.md)). Format follows
[Keep a Changelog](https://keepachangelog.com/); the project is in the
pre-release phase, so milestones are tagged `pre-v0.1.x` until the public
`0.1.0`.

## [pre-v0.1.19] — 2026-09-04 — grounding disclosure + opt-out in the UI

Feature commit: `0957156` (surface registry grounding per compose and let
users opt out of the tools).

- **Grounding disclosure** — the compose-timing strip under the task bar now
  reports how grounded each live compose was: `🔧 verified via N registry
  lookups` when the decompose agent used the tools, `prompt-based — no
  registry lookups` when it answered from the prompt (count comes from the
  done event and is persisted on history entries, so reopening a pipeline
  keeps the disclosure).
- **Grounding toggle in the compose box** (live mode) — default ON follows
  the measured auto-policy (fresh composes verify via registry tools, seeded
  variations stay prompt-only); OFF sends `tools_enabled: false` on the
  wire so every compose runs prompt-only and fast (~30s vs ~60-100s).
- **API** — `TaskRequest.tools_enabled` (None = auto, False = prompt-only,
  True = force grounding) threads through `/api/compose`, `/api/compose/silent`,
  and the SSE stream to the agent.
- **Tests** — hermetic 84 → **86** (opt-out reaches the agent: `tool_calls`
  0 on compose and stream, no tool lines; default keeps the fake's two
  lookups); browser E2E 9 → **10** — `test_grounding_e2e` stubs the stream
  with `tool_calls: 4` then 0: the verified line renders, the toggle flip
  renders the prompt-based line, and the wire bodies prove the grounded
  default omits `tools_enabled` while the opt-out sends `false`.

## [pre-v0.1.18] — 2026-09-04 — measured tool policy for compose

Feature commits: `82a5e9e` (tool prompt tuning) + `c60924f` (seed-aware tool
default) — registry tool use measured live and scoped to where it pays.

- **Live A/B on seeded form-factor crossings** — 12 real seeded G1→Go2
  variations (perception-flavored patrol and a sharp manipulation-flavored
  push task): the capability gate rejected **0/12 with or without tools**,
  and the model swapped the seed's arm skill (`motion-generation`) for the
  quadruped-class `legged-manipulation` in every run. The old 1/3
  copy-rate is gone — the quadruped catalog + variation rules matured — so
  tools add no measured gate benefit on the seeded path.
- **Tuning** — grounded composes cost ~3× latency (54–78s vs 21–27s)
  because the model re-read catalog rows already in its system prompt, one
  `get_skill` round at a time (21 calls on a fresh compose). The model
  cannot emit parallel tool calls on this endpoint (probed), so the rules
  now forbid re-reading the catalog and limit calls to
  `check_capability` on doubtful anatomy only. Fresh unseeded compose
  dropped **21 → 2 calls** with the same valid result.
- **Seed-aware default** — `decompose_task` auto-selects the path: fresh
  decomposes keep the tools (grounding is real there); seeded variations
  run prompt-only and stay fast. Verified live: seeded Go2 push variation
  composes in ~36s with `tool_calls: 0`, still swapping correctly.
  `tools_enabled` forces either path for future A/B.
- **Tests** — hermetic suite 83 → **84**: seeded decomposes send no tool
  schemas by default while fresh decomposes keep them.

## [pre-v0.1.17] — 2026-09-04 — registry tool use in compose

Feature commit: `9c0473e` (the decompose agent queries skill/robot registries
as structured tools, grounding plans in registry data).

- **Registry tools** — the compose round-trip now offers the agent four
  structured tools backed by the exact registries the capability gate
  validates against: `list_skills` (compact rows), `get_skill`, `get_robot`,
  and `check_capability` (does this skill's required anatomy exist on this
  robot?). Tool calls execute in a bounded loop (max 12 rounds, escaped via
  a hard cap) and results feed back as tool messages before the final JSON.
- **Grounding instead of memory** — the model can verify costs, GPU needs,
  and anatomy mid-decomposition rather than trusting the catalog text baked
  into the prompt. The catalog stays in the prompt as a safety net, so
  providers that reject tool definitions (HTTP 400/404/422) degrade to the
  prompt-only path instead of failing the compose.
- **Observability** — every registry lookup surfaces in the reasoning stream
  as a `🔧 queried …` line, and every compose response (stream done event,
  `/api/compose`, `/api/compose/silent`) reports its `tool_calls` count.
  `live_check journey` hard-checks the field and prints how grounded the
  compose was.
- **Resilience fixes found live** — tool round-trips inflate the context the
  model must answer over; output budget raised 2000 → 4000 tokens (empty
  content + `finish=length` after a large tool payload) and `list_skills`
  returns compact rows so the round-trip stays lean.
- **Tests** — hermetic suite 77 → **83**: executor grounded in the
  registries (go2 × motion-generation → incompatible), the tool loop feeds
  results back and reports every call, a provider rejecting tools degrades
  cleanly, the loop is bounded, the default budget covers a 9-round
  verification-heavy plan, and the stream surfaces tool lines + the done
  event's `tool_calls`.

## [pre-v0.1.16] — 2026-09-04 — dry-run verdicts on history cards

Feature commit: `2098369` (persist the last simulation dry-run verdict so a
reopened pipeline shows its test result without re-running).

- **Dry-run verdict persistence** — every completed simulation dry-run is
  recorded onto the history entry being displayed (scenario seed, compressed
  elapsed time, per-step pass/fail verdicts). History cards gain a badge:
  `🧪 pass · 14s · 0x0007` (green) or `🧪 fail · …` (red), with a tooltip
  naming the pass count and seed.
- **Instant restore on reopen** — reopening a pipeline and running sim
  dry-run renders the stored verdict immediately ("last run · completed in
  14s …") with the same seed chip, instead of replaying the ~14s run. The
  stored view is only honored while it matches the current plan: if steps
  were edited after the run, the stale record is discarded and the panel
  auto-replays live, so a verdict can never be shown for a different plan.
- **Tests** — browser E2E (9 total): the new dry-run persistence test
  asserts the card badge appears after a run, reopening renders the stored
  verdict within 3s with the "last run" framing and the same seed, and
  replaying from the stored state reproduces the identical summary.

## [pre-v0.1.15] — 2026-09-04 — simulation dry-run panel

Feature commit: `6b21fa4` (replay a pipeline step-by-step with simulated
pass/fail against skill metadata).

### Added
- **Simulation dry-run** — the results view gains a "▶ sim dry-run" action
  next to edit/variation that replays the composed pipeline step-by-step
  with real wall-clock pacing and per-step verdicts derived from skill
  metadata. Structural checks (robot anatomy vs skill requirements; step
  ordering — validation or deployment before any training step, data
  generated after training already started, deployment not last) fail
  deterministically; every remaining step carries a small seeded execution
  risk (training can diverge, validation can fall short). Same plan + same
  seed = same outcome; "🎲 new scenario" rerolls the execution risk.
- **Honest framing** — the panel header states it is a metadata replay, not
  Isaac Sim; a preflight scan announces structural issues before the replay
  starts; the run halts at the first failing step and only executed steps
  charge cost; the seed chip makes results reproducible.
- **Replay controls** — pause/resume freezes the real clock mid-step, replay
  re-runs the identical scenario, and closing/reopening rolls a fresh seed.
- **Tests** — new browser E2E composes a mock pipeline, asserts the replay
  completes with verdict chips, pause freezes the elapsed clock, a same-seed
  replay reproduces the identical summary, and an edit that moves
  policy-validation ahead of every training step halts the replay at step 1
  with the structural reason. Suite counts: 77 hermetic, 8 browser E2E.

## [pre-v0.1.14] — 2026-09-04 — compose time on history cards

Feature commit: `bd6db86` (surface compose wall time on live history cards).

### Added
- **Live history entries keep their compose stats** — the history snapshot
  for every live compose (fresh or seeded variation) persists its wall time,
  retry count, and per-phase breakdown alongside the pipeline, so the info
  survives reloads and Redis refreshes.
- **Cards show it** — the meta row of a live card gains "⏱ 11s · retried
  1×" (warn-colored when the compose healed retries, with a full tooltip);
  mock cards and older entries without stats show nothing extra.
- **Reopen restores the disclosure** — "open in editor" on a live card now
  restores the compose-timing line under the task bar (total + per-phase
  breakdown, with the retry disclosure), so a user returning to a slow
  pipeline still sees how long its compose took — previously the strip only
  appeared for fresh composes.
- **Tests** — the retry-note browser E2E now asserts the newest card's badge
  reads "11s" with the right retry count (1× then 3×) and that reopening the
  card re-renders the full timing line. Suite counts unchanged: 77 hermetic,
  7 browser E2E.

## [pre-v0.1.13] — 2026-09-04 — compose telemetry on /api/health

Feature commit: `f678071` (expose rolling compose latency/retry telemetry
on /api/health).

### Added
- **Rolling compose telemetry ring** — every finished compose
  (`/api/compose`, `/api/compose/silent`, `/api/compose/stream`) appends its
  wall time and healed-retry count to a thread-safe in-process ring of the
  last 20, so ops can see live-mode health without standing up external
  metrics.
- **`compose_stats` on /api/health** — `samples`, `avg_seconds`, `p95_seconds`,
  `avg_retries`, `retried_composes`, and the tail of the ring (last 10
  entries with endpoint / seconds / retries / timestamp); `{samples: 0}`
  before the first compose of a process.
- **`live_check journey` prints it** — the health section now shows
  `compose_stats: samples / avg / p95 / retried` from the running server.
- **Tests** — 3 new hermetic tests: health reports sane aggregates + the
  stream entry after a real (fake-agent) compose; a retried stream compose
  shows up with `retries: 1`; and the ring stays capped at 20 entries.
  Suite counts: 77 hermetic, 7 browser E2E.

## [pre-v0.1.12] — 2026-09-04 — slow-compose warning

Feature commit: `60f1904` (warn when a compose beats the session's moving
time baseline).

### Added
- **Moving-baseline slow detector** — live compose wall times accumulate per
  tab session (`sf-session-compose-times`, capped at 6); once two composes
  have established a baseline, any compose that clears a 12s floor and is
  2×+ the session's recent **median** triggers a warn note: "compose took
  60s — 4.6× slower than your recent typical (13s). retry, or simplify the
  task." Because the baseline is the session's own median, the threshold
  adapts to how long composes normally take here instead of a fixed
  constant.
- **Mirrors the frequent-blip hint** — same amber strip styling and
  placement (beside the compose-mode switch in the input view and in the
  results view), cleared by the next normal compose and by switching to
  mock mode. Unaffected by (and complementary to) the per-compose timing
  strip and the auto-retry disclosures.
- **Tests** — seventh browser E2E: seeds a two-compose session baseline
  (12s/14s), reloads same-tab, intercepts the compose stream with a 60s
  done event and asserts the note reads "4.6× slower than your recent
  typical (13s)", then a normal (10s) compose clears it and the session
  history records both runs. Suite counts: 74 hermetic, 7 browser E2E.

## [pre-v0.1.11] — 2026-09-04 — per-phase compose timing

Feature commit: `62f8c9c` (break compose timing into decompose/explain/logs
phases).

### Added
- **Per-phase wall times on the done event** — the SSE compose stream times
  each round-trip group separately and the `done` event carries
  `phases: {decompose, explain, logs}` (seconds, each including its own
  retry backoff; `logs` is the simulated execution stream). The whole-run
  `seconds` total is unchanged.
- **Breakdown in the results view** — the compose-timing strip now shows a
  second, fainter line under the total: "decompose 19s · explain 5s · logs
  7s" — users see that the model round-trips (not the UI) dominate instead
  of one opaque number.
- **Tests** — the clean and retried compose-stream hermetic tests assert the
  done event's `phases` dict names exactly the three keys with `logs > 0`
  (the simulated stream always takes real time); the retry-note browser E2E
  stub now carries phases and asserts the breakdown line renders for both
  the retries=1 and retries=3 composes. Suite counts unchanged: 74 hermetic,
  6 browser E2E.

## [pre-v0.1.10] — 2026-09-04 — retry counts on request/response endpoints

Feature commit: `72804ed` (report auto-retry counts on
compose/silent/improve responses).

### Added
- **`retries` on non-stream responses** — `/api/compose` (summed across its
  decompose + explain round-trips), `/api/compose/silent`, and
  `/api/improve` now carry `retries` in their JSON (0 on clean calls), so
  request/response API clients see healed LLM blips the same way the SSE
  stream's `done` event reports them — previously the count existed only on
  the streaming path the UI uses.
- **`live_check` reports it** — the journey command checks that compose
  responses carry the count and prints "auto-retried N× during this compose
  (healed on its own)" when N > 0; the share-links bonus compose prints the
  same note.
- **Tests** — 4 new hermetic tests: clean compose / compose-silent / improve
  all report `retries: 0`, compose sums retries across both round-trips,
  silent reports multi-retry decomposes, and improve reports healed
  suggestion round-trips. Suite counts: 74 hermetic, 6 browser E2E.

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
