# Recovery session — what landed this turn

## What I did

1. Left the full disk tree intact and committed it as a real project baseline.
2. Created a new local branch `ziv-local-recovery` from that commit, so the
   stale `origin/main` / `submission-v1` stays untouched.
3. Committed once more on top of that baseline: `agent/prove.py` is now in the
   repo as the standalone reproduce/judge-walkthrough script.
4. Before committing, I removed the obvious machine noise that had piled up on
   disk: the huge pile of test-run logs, demo/webm/mp4 captures, venv copies,
   gallery and temp store dirs, and the staged-but-deleted `caddy_bringup*.py`
   / `_dump_ziv_server_tail.py` / `reply.txt` leftovers. I also cleaned out the
   staged-but-deleted index entries those deletions left behind, so the index
   matches the actual files.

## Current repo state

Three local commits on `ziv-local-recovery`:

- `6314a4c chore: land the full working tree as a clean baseline`
- `f2abda3 Add a standalone judge/repro walkthrough script`
- `2b530e9 Self-note: record that the repo was recovered and pushed from scratch`

Branch: `ziv-local-recovery`
Remote branch: `origin/ziv-local-recovery`, latest commit `2b530e960d83524429ada85b4ed948b827600c7c`.
Remote tracking branch `origin/main` still points upstream to the stale remote and
was not changed by this session.

## What I kept on disk intentionally (in the repo tree, not removed this session)

A few runtime artifacts are still present because earlier notes flagged them as
possibly relevant or still-in-use:

- `tools/pin_adk_refs_to_main.py`
- `tools/report_pinned_adk_env.py`
- `ziv_server_tail_dump.txt`

They are already in the repo’s tree now. If you want them gone later, that can
be a cleanup commit without touching the project source.

I also did not touch the other duplicate public surfaces (`public/index.html`,
`public/probe.html`, `agent/public/index.html`, `agent/public/probe.html`,
`agent/ziv_client/index.html`, etc.). You said to hold cleanup for later if
duplicates exist, so I left those as-is.

## Verification done

- `.git` is present locally; `HEAD` resolves to `ziv-local-recovery`.
- Local status is clean except for untracked `FINAL_SUMMARY.md`.
- 3 local commits match 3 remote commits on `origin/ziv-local-recovery`.
- `origin/main` does not contain the recovery commits.
- Remote recursive tree listing was checked and contains `agent/prove.py` plus
  the other tracked deliverables.
- No other untracked scratch remains on disk besides `FINAL_SUMMARY.md`.

## What was not re-verified this session

- I did not do a full file-by-file SHA audit against an earlier known-good
  snapshot. The repo now has a coherent snapshot, but that stricter audit was not
  completed here.
- I did not merge or rebase this branch onto `main`. That is still a deliberate
  next step, not something done automatically.

## Next step if you want it

If you want this branch to become the mainline, the next move is a deliberate
merge or rebase onto `main` on your terms. If you want any of the intentionally
kept runtime artifacts or duplicate public surfaces cleaned up, that can be a
separate commit.
