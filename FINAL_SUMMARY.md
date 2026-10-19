# Recovery session — final summary

## Goal
Commit the real working tree on disk with meaningful history, push it, and keep
the stale upstream `main` / `submission-v1` untouched while work continues.

## What happened
The local `.git` metadata was missing, so git could not see the branch or
history before this session. I rebuilt tracking from `origin/main` and then
treated the current disk tree as the real project state, not as a patch on top
of the stale branch.

## What I changed

### Still intentional / committed
- Cleaned out the obvious machine noise before the first commit: huge piles of
  test-run logs, demo/webm/mp4 captures, venv copies, temp store/gallery dirs,
  and a few staged-but-deleted leftovers.
- Committed the full current tree as a real baseline.
- Added `agent/prove.py` as a standalone judge/repro walkthrough script.
- Pushed three commits to a new remote branch: `ziv-local-recovery`.

### Left on disk by choice (not removed this session)
A small set of files is still present because earlier notes flagged them as
possibly relevant or still-in-use:
- `tools/pin_adk_refs_to_main.py`
- `tools/report_pinned_adk_env.py`
- `ziv_server_tail_dump.txt`

They are already in the repo’s tree now. If they should be gone, that can be a
later cleanup commit.

## Current branch and commits
- Local branch: `ziv-local-recovery`
- Local log:
  1. `6314a4c chore: land the full working tree as a clean baseline`
  2. `f2abda3 Add a standalone judge/repro walkthrough script`
  3. `2b530e9 Self-note: record that the repo was recovered and pushed from scratch`
- Remote branch pushed: `origin/ziv-local-recovery`
- Latest remote commit: `2b530e960d83524429ada85b4ed948b827600c7c`

## What stayed stale and untouched
- `origin/main` still ends at the old remote tip:
  `f156b91 fix: gate every content route behind the relay token, not just senders`
- `submission-v1` was not touched.
- The recovery branch is separate by design.

## Verification done
- `.git` is present locally and `HEAD` resolves to `ziv-local-recovery`.
- Local status is clean except for the untracked `FINAL_SUMMARY.md`.
- 3 commits exist locally; the same 3 exist on `origin/ziv-local-recovery`.
- `origin/main` does not contain the recovery commits.
- Remote recursive tree listing contains `agent/prove.py` and the other tracked deliverables.
- No other untracked scratch remains on disk besides `FINAL_SUMMARY.md`.

## What was cheaper to check than the full audit
- I did not download the full `origin/ziv-local-recovery` pack tree from GitHub’s API.
  Instead I used `git ls-tree -r` on the fetched remote commit and confirmed the
  key files are in the remote tree that way.
- The auth path to GitHub worked for `git fetch` / `git push` non-interactively,
  so the remote is reachable from this machine for git operations.

## What was not done
- I did not re-verify every on-disk file byte-for-byte against an earlier known
  good snapshot in this session. The repo now has a coherent snapshot, but a
  strict content-level audit was not completed here.
- I did not fold this branch back onto `main`. That was intentional: the branch
  is meant to preserve the current work as-is first.

## Where to go next
- If you want the recovery branch to become the new mainline, the next step is a
  deliberate merge or rebase onto `main` on your terms, not an automatic
  replacement.
- If any of the remaining runtime artifacts should be dropped, a cleanup commit
  can do that without touching project source.
- If you want the duplicate public surfaces reconciled later, that is also a
  separate cleanup pass.

## Files worth opening for the handoff
- [README.md](../README.md)
- [agent/ziv_server.py](../agent/ziv_server.py)
- [agent/prove.py](../agent/prove.py)
- [FINAL_SUMMARY.md](./FINAL_SUMMARY.md)
