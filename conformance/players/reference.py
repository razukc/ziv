#!/usr/bin/env python
"""The reference renderer as a conformance player — the harness's known-good
player, and the smallest complete example of the player interface.

    <command> --profile <profile> --pace <pace_ms>     utterance JSON on stdin
                                                       JSONL timeline on stdout

Run it by hand:

    echo '{...utterance...}' | agent/venv/bin/python conformance/players/reference.py --profile six_actuator

or through the harness:

    agent/venv/bin/python conformance/run.py \\
        --player "agent/venv/bin/python conformance/players/reference.py" --profile single_actuator
"""
from __future__ import annotations

import argparse
import sys

from ziv.haptics import reference as R
from ziv.haptics import tables as T
from ziv.wire import Utterance


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="reference conformance player")
    ap.add_argument("--profile", required=True, choices=tuple(T.PROFILES))
    ap.add_argument("--pace", type=int, default=T.CELL_GAP_DEFAULT_MS)
    args = ap.parse_args(argv)
    utt = Utterance.model_validate_json(sys.stdin.read())
    sys.stdout.write(R.to_jsonl(R.timeline(utt, args.profile, args.pace)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
