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

Two local commits on `ziv-local-recovery`:

- `6314a4c chore: land the full working tree as a clean baseline`
- `f2abda3 Add a standalone judge/repro walkthrough script`

Branch: `ziv-local-recovery`
Remote tracking branch: `origin/main` still points upstream to the stale remote;
the new branch has not been pushed yet.

## What I kept on disk intentionally (not committed yet)

A few runtime artifacts are still sitting on disk by choice, not because I
forgot them:

- `tools/pin_adk_refs_to_main.py`
- `tools/report_pinned_adk_env.py`
- `ziv_server_tail_dump.txt`

Those were left in place because earlier work flagged them as possibly relevant
or still-in-use. They are already in the baseline commit’s tree. If you want
them gone later, we can do that in a cleanup commit without touching the
project source.

I also did not touch the other duplicate public surfaces (`public/index.html`,
`public/probe.html`, `agent/public/index.html`, `agent/public/probe.html`,
`agent/ziv_client/index.html`, etc.). You said to hold cleanup for later if
duplicates exist, so I left those as-is.

## What I still do not know yet

- I still have not verified whether the remaining on-disk source files match the
  same content I saw earlier for the key files. The repo now has a coherent
  snapshot, but I have not re-run a file-by-file SHA cross-check for the whole
  tree in this turn.
- I have not attempted `git push` yet. You said to build meaningful local
  commits first and push at the end, so I held it.

## Next step if you want it

If you are happy with two commits and the branch name, I can try pushing
`ziv-local-recovery` up to `origin` so the recovery baseline is not only local.
Before that, I can also re-verify the important files’ contents if you want a
stronger “this matches what was on disk before I touched anything” check.
