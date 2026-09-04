# Contributing

Single-developer hackathon project, so this stays lightweight. The rules below
exist for one reason: with everything committed locally on `main`, the commit
history and the checkpoint tags are how we track each pre-v0.1.0 iteration.

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/). A
commit message looks like:

```
<type>(<scope>): <imperative summary, lowercase, no trailing period>

<why — what problem this solves or behavior it changes>

<optional footer>
```

**Types**

| Type     | When to use                                                        |
|----------|---------------------------------------------------------------------|
| `feat`   | A user-visible capability (compose, edit, theme, share links…)      |
| `fix`    | A bug fix — behavior changes to correct something                   |
| `refactor` | Same behavior, cleaner structure (extract a module, rename…)      |
| `docs`   | README, SECURITY, this file, CHANGELOG, roadmap                      |
| `test`   | New or changed tests only                                            |
| `chore`  | Tooling, deps, gitignore, scripts — nothing user-visible             |

**Scopes** (optional, pick the closest): `frontend`, `backend`, `tests`,
`docs`, `infra`. Examples:

```
feat(frontend): persist pipeline history across reloads
fix(backend): resolve exported pipelines from inline payload when id is stale
test(tests): cover history reopen -> edit -> re-export in a browser E2E
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
- A milestone is *verified* when: `tsc --noEmit` is clean, the hermetic suite
  passes from `agent/` (`python -m pytest`), browser E2E passes when servers
  are up (`python -m pytest -m e2e`), and README/CHANGELOG test counts and
  feature text match reality.
- Each milestone gets a `## [pre-v0.1.x]` entry in `CHANGELOG.md`.
- Naming is **not final**: SkillForge is a working title. Decide the public
  name before cutting `0.1.0`; the docs/`README.md`/`DEVPOST.md` rename
  happens as one `chore` or `feat` commit at that point.

## Before you commit

1. `cd frontend && npx tsc --noEmit`
2. `cd agent && python -m pytest -q` (hermetic suite — currently 70 tests — passes, e2e deselected)
3. `cd agent && python -m pytest -m e2e` if the backend (:8000) and frontend
   (:3000) are running (5 tests, ~2 min)
4. Live checks against real services: `python live_check.py journey|edit`
   (costs real LLM credits — run deliberately, not on every change)
5. Behavior changed → add a `CHANGELOG.md` entry under `[Unreleased]` or the
   current milestone
6. Commit with a conventional message, then push nothing (no remote yet)

## Docs map

| File             | Purpose                                        |
|------------------|------------------------------------------------|
| `CHANGELOG.md`   | What shipped per milestone tag                  |
| `docs/ROADMAP.md`| What's planned, with statuses                   |
| `README.md`      | Project overview + quick start                  |
| `SECURITY.md`    | Security model and reporting                    |
