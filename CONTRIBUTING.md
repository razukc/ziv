# Contributing

Single-developer project, so this stays lightweight. The rules below exist for
one reason: with everything committed locally on `main`, the commit history
and the checkpoint tags are how we track each pre-v0.1.0 iteration.

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
| `feat`     | A user-visible capability (relay, client, firmware, feel…)     |
| `fix`      | A bug fix — behavior changes to correct something              |
| `refactor` | Same behavior, cleaner structure (extract a module, rename…)   |
| `docs`     | README, this file, CHANGELOG, roadmap, specs                   |
| `test`     | New or changed tests only                                      |
| `chore`    | Tooling, deps, gitignore, scripts — nothing user-visible       |

**Scopes** (optional, pick the closest): `server`, `client`, `firmware`,
`tools`, `docs`, `infra`. Examples:

```
feat: mark the freeing close on the wire and prove the redial end to end
fix(server): peek the inbox under the turn lock so deliveries can't double
test: prove the gate's threaded stampede queues without loss
```

Rules that matter:

- **One logical change per commit.** Don't mix a fix with an unrelated feat.
- **Subject ≤ ~72 chars, imperative mood** ("add X", not "added X" / "adds X").
- **Body explains why**, not what — the diff already shows what.
- Keep the `Co-Authored-By` footer when a commit is co-authored; never alter
  `git config`.
- Never commit secrets (`agent/.env` is ignored — see `.gitignore`) or
  unrelated local edits.

## Checkpoint tags and versioning

Everything before the public 0.1.0 is the pre-release phase, tracked with
lightweight tags:

```
git tag pre-v0.1.0    # initial baseline
git tag pre-v0.1.1    # next verified milestone
```

- Tag a **milestone** (a coherent, verified feature/iteration), not every
  commit. The history in between stays readable via plain commits.
- A milestone is *verified* when: the hermetic suite passes from `agent/`
  (`python -m pytest`), the browser e2e passes when run deliberately
  (`python -m pytest -m e2e`), firmware checks pass
  (`python firmware/app/ziv_qemu/run_ziv_tests.py` when firmware changed),
  and README/CHANGELOG test counts and feature text match reality.
- Each milestone gets a `## [pre-v0.1.x]` entry in `CHANGELOG.md`.
- The cut discipline: verify → commit the work → convert `[Unreleased]` →
  tag the cut commit.

## Before you commit

0. Install the pre-commit hook once per clone: `git config core.hooksPath hooks`
   — it runs the haptic timing verify (`python tools/haptic_timing.py`) and the
   haptic_out bench suite, and blocks any commit that would ship spec drift
1. `cd agent && python -m pytest -q` — the hermetic suite (browser e2e
   deselected); includes the timing drift guard, the seam/threading tests,
   the server + store suites, and the demo-chain generation tests
2. `cd agent && python -m pytest -m e2e` if you changed the client or the
   server's turn path (Playwright, real Chrome, ~30 s)
3. Firmware changed → `python firmware/app/ziv_qemu/run_ziv_tests.py`
4. Timing spec changed → `python tools/haptic_timing.py --write` and commit
   the regenerated consumers together with the JSON — the drift guard will
   not let them desync
5. Behavior changed → add a `CHANGELOG.md` entry under `[Unreleased]` or the
   current milestone
6. Commit with a conventional message, then push nothing (no remote yet)

The haptic timing guard is belt-and-suspenders: the pre-commit hook blocks
at commit time, the hermetic suite (`agent/tests/test_haptic_timing.py`)
fails in local runs even if a hook is never installed, and GitHub Actions
(`.github/workflows/ci.yml`) runs the same verify + the full Ziv suite on
every push. Drift cannot be committed or pushed either way.

## Docs map

| File | Purpose |
|------|---------|
| `CHANGELOG.md` | What shipped per milestone tag |
| `docs/ROADMAP.md` | What's planned, with statuses |
| `docs/HAPTIC_COMPANION_PLAN.md` | The product plan — invariants, phases, BOM |
| `docs/HAPTIC_TIMING_SPEC.md` | The feel-timing spec and its generated consumers |
| `docs/QEMU_SIMULATION_LADDER.md` | Bench → QEMU rungs, the promote-a-check discipline |
| `docs/HARDWARE_BRINGUP.md` | Six-actuator on-wrist bring-up |
| `README.md` | Project overview + quick start |
