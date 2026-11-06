# Contributing

Single-developer project, so this stays lightweight. The rules below exist for
one reason: with everything committed locally, the commit history and the
checkpoint tags are how we track each pre-v0.1.0 iteration.

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/). A
commit message looks like:

```
<type>(<scope>): <imperative summary, lowercase, no trailing period>

<why — what problem this solves or behavior it changes>

<optional footer>
```

**Types**

| Type       | When to use                                                   |
|------------|----------------------------------------------------------------|
| `feat`     | A user-visible capability (relay, client, console, firmware…)  |
| `fix`      | A bug fix — behavior changes to correct something              |
| `refactor` | Same behavior, cleaner structure (extract a module, rename…)   |
| `docs`     | README, this file, CHANGELOG, roadmap, specs                   |
| `test`     | New or changed tests only                                      |
| `chore`    | Tooling, deps, gitignore, scripts — nothing user-visible       |

**Scopes** (optional, pick the closest): `relay`, `client`, `console`,
`firmware`, `spec`, `conformance`, `tools`, `docs`, `infra`. Older history
uses `server` for the relay. Examples:

```
feat(relay): the sequencing relay — pure core, SQLite outbox, factory-built app
fix(firmware): write the mux control byte as a one-hot mask so dot 1 can be selected
test(core): prove the outbox loses and duplicates nothing under failover
```

Rules that matter:

- **One logical change per commit.** Don't mix a fix with an unrelated feat.
- **Subject ≤ ~72 chars, imperative mood** ("add X", not "added X" / "adds X").
- **Body explains why**, not what — the diff already shows what.
- Keep the `Co-Authored-By` footer when a commit is co-authored; never alter
  `git config`.
- Never commit secrets (`.env` at the root is ignored — see `.gitignore`),
  wearer data (`ziv_data/` is ignored) or unrelated local edits.

## Checkpoint tags and versioning

Everything before the public 0.1.0 is the pre-release phase, tracked with
lightweight tags:

```
git tag pre-v0.1.0    # initial baseline
git tag pre-v0.1.1    # next verified milestone
```

- Tag a **milestone** (a coherent, verified feature/iteration), not every
  commit. The history in between stays readable via plain commits.
- A milestone is *verified* when: the Python suite passes
  (`.venv/bin/python -m pytest -q`), the browser tier passes when run
  deliberately on a host with Chromium (`.venv/bin/python -m pytest -m e2e tests/e2e`),
  the front ends pass (`npm test` in `client/` and `console/`), the firmware
  runners pass when firmware changed, the conformance oracle and the drift
  guard are in sync, and README/CHANGELOG test counts and feature text match
  reality.
- Each milestone gets a `## [pre-v0.1.x]` entry in `CHANGELOG.md`.
- The cut discipline: verify → commit the work → convert `[Unreleased]` →
  tag the cut commit.

## Before you commit

0. Install the pre-commit hook once per clone: `git config core.hooksPath hooks`.
   It runs the timing drift guard (`python tools/haptic_timing.py`), the
   wire-schema diff (`python -m ziv.wire` against `schema/`), the conformance
   oracle check (`python conformance/run.py --check`) and the `haptic_out`
   bench, and blocks any commit that would ship drift between the spec, the
   contract, the oracle and their generated outputs
1. `.venv/bin/python -m pytest -q` — core, store, relay, reference renderer,
   conformance, the timing guard, and the integration tests that drive the
   headless device from `client/dist` (build the client first, or they skip)
2. Client or console changed → `npm test` and `npm run typecheck` in that
   directory; a renderer change also needs
   `.venv/bin/python conformance/run.py --player "node client/dist/conformance.js" --profile <P>`
   on both profiles
3. `ziv/wire.py` changed → `.venv/bin/python -m ziv.wire schema/`, then
   `cd console && npm run gen:types`; commit the schemas and the generated
   types with the change (the console build refuses stale types)
4. Timing spec changed → `python3 tools/haptic_timing.py --write`, then
   `.venv/bin/python conformance/run.py --write`; read the diff of
   `conformance/expected/` (it is the felt change, beat by beat) and commit
   the JSON, the regenerated consumers and the expected timelines together
5. Firmware changed → `python3 firmware/haptic_out/run_tests.py`,
   `python3 firmware/app/ziv_qemu/run_ziv_tests.py` and
   `python3 firmware/band/run_band_tests.py`
6. Client or console changed in a way a browser would show →
   `.venv/bin/python -m pytest -m e2e tests/e2e` on a host where Chromium
   launches (it skips otherwise)
7. Behavior changed → add a `CHANGELOG.md` entry under `[Unreleased]` or the
   current milestone; counts come from the run you just made
8. Commit with a conventional message

The guards are belt-and-suspenders: the pre-commit hook blocks at commit
time, the suite (`tests/test_timing_guard.py`, `tests/test_conformance.py`)
fails in local runs even if a hook is never installed, and GitHub Actions
(`.github/workflows/ci.yml`) runs the same checks plus every suite on every
push to `main` or `product`. Drift cannot be committed or pushed either way.

## Docs map

| File | Purpose |
|------|---------|
| `README.md` | Project overview, quick start, the suites, security, honest limits |
| `CLAUDE.md` | The map of the tree and the rules that bind contributors |
| `CHANGELOG.md` | What shipped per milestone tag; `[Unreleased]` for the current work |
| `docs/ROADMAP.md` | What's shipped and what's next, with statuses |
| `docs/ARCHITECTURE.md` | The architecture the tree implements; §13 records how it was reached |
| `docs/HAPTIC_COMPANION_PLAN.md` | The product plan — invariants, phases, BOM |
| `docs/HAPTIC_TIMING_SPEC.md` | The feel-timing spec and its generated consumers |
| `conformance/README.md` | The oracle, the golden set and the player interface |
| `client/README.md` | The web renderer, its headless driver and its limits |
| `console/README.md` | The console, its routes and its accessibility checklist |
| `firmware/band/README.md` | The band as a device renderer; what runs where; what is unverified |
| `firmware/haptic_out/README.md` | The sequencer and the bench |
| `docs/QEMU_SIMULATION_LADDER.md` | Bench → QEMU rungs, the promote-a-check discipline |
| `docs/HARDWARE_BRINGUP.md` | Six-actuator on-wrist bring-up |
| `docs/COMMUNITY_SETUP.md` | Discussions, the feedback form, what landed where |
