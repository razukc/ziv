# Reproduce the Ziv judge walkthrough from a standalone relay checkout

Purpose: give a second machine (or a future you) a deterministic command that
rebuilds the same proof surface the repo is supposed to present, without
depending on the exact runtime state in `agent/`.

What this reproduces:
- A fresh `agent/ziv_data/` store in a temp dir
- The relay app started on a free local port
- A dev-band WebSocket attached
- One typed message and one audio-stub injection, each observed on the wire
- The /api/ziv/timing endpoint asserted to match the generated module
- A short health snapshot dumped for the runner

This is the same shape the repo documents elsewhere; this file is just the
mechanically reproducible version of it.

Run it from the repo root:

    python agent/prove.py

Exit code 0 means the suite produced its expected wire frames and timings.
Non-zero means something in the checkout cannot stand on its own.
