"""model_probe.py — one real call to the agent path, for the required
Nemotron output-quality rating in DEVPOST_FIELDS.md §4.

The submission's graded questionnaire asks "how would you rate Nemotron's
output quality for your use case (1–10)". Answering that honestly means
running the model once and looking at what it actually produced for *this*
channel — not quoting the model card. That is all this does: it calls the
relay's own compose function, so what you read here is byte-for-byte what
the wrist would spell.

It also prints the two numbers that decide the rating for a haptic turn:
the length of the line (a wrist spells one cell at a time, so length is
the binding constraint, not fluency) and the round-trip time (a turn has a
latency ceiling a chat window does not — past a few seconds the wearer
feels working ticks instead of silence).

Run from the repo root:

    python tools/model_probe.py
    python tools/model_probe.py --repeat 3     # determinism at temperature 0

Needs NEBIUS_API_KEY in agent/.env (the relay loads it the same way).
Exits non-zero if the call fails — the loud-not-silent rule applies here
too: a probe that cannot reach the model must not print a rating.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))


def _load_env() -> None:
    """Read agent/.env into the environment without overriding real vars."""
    env = ROOT / "agent" / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


INTENTS = [
    "meds at nine tonight",
    "the taxi is outside",
    "call your mother back",
]


async def _probe(repeat: int) -> int:
    _load_env()
    import ziv_server as zs

    if not zs.agent_path_available():
        print("FAIL: no key or model configured — nothing was probed.")
        print(f"  NEBIUS_API_KEY set: {bool(zs.NEBIUS_API_KEY)}")
        print(f"  ZIV_TEXT_MODEL:     {zs.ZIV_TEXT_MODEL or '(unset)'}")
        return 1

    print(f"model:  {zs.ZIV_TEXT_MODEL}")
    print(f"base:   {zs.NEBIUS_BASE_URL}")
    print()

    lines: list[str] = []
    latencies: list[float] = []
    try:
        for _ in range(repeat):
            for intent in INTENTS:
                started = time.perf_counter()
                out = await zs.compose_reminder_line(intent)
                elapsed = time.perf_counter() - started
                latencies.append(elapsed)
                lines.append(out)
                print(f"  {elapsed:6.2f}s  intent {intent!r:28} -> {out!r}")
    except zs.HTTPException as exc:
        print(f"\nFAIL: the call did not succeed ({exc.status_code}): {exc.detail}")
        print("      Rate nothing on a call that failed — fix this first.")
        return 1

    lengths = [len(line) for line in lines]
    print()
    print(f"calls:      {len(lines)}")
    print(f"length:     min {min(lengths)} / median "
          f"{sorted(lengths)[len(lengths) // 2]} / max {max(lengths)} chars")
    print(f"latency:    min {min(latencies):.2f}s / median "
          f"{sorted(latencies)[len(latencies) // 2]:.2f}s / max "
          f"{max(latencies):.2f}s")
    print(f"distinct:   {len(set(lines))} of {len(lines)} lines "
          f"(at temperature 0, repeats of one intent should match)")
    print()
    print("Paste the shortest line and the median latency under the")
    print("output-quality answer in DEVPOST_FIELDS.md, then give the number.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--repeat", type=int, default=1,
        help="how many times to send each intent (default 1)",
    )
    args = ap.parse_args()
    if args.repeat < 1:
        ap.error("--repeat must be >= 1")
    return asyncio.run(_probe(args.repeat))


if __name__ == "__main__":
    raise SystemExit(main())