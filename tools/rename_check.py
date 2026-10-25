#!/usr/bin/env python3
"""rename_check.py — validate protocol §5 option-B rename candidates against the mark arc.

Option B keeps the haptic mark and changes the word, so a candidate is legal
only if its letters spell the same dot-count arc as the current mark.  This
tool makes that check mechanical — the same `rename_word_problems()` engine
the timing checker uses to validate the spec itself — so no candidate is
hand-waved into `rename_examples`.

Usage:
  python tools/rename_check.py tin wiz       # check candidates (exit 0/1)
  python tools/rename_check.py nawtin -a     # validate, then add to the spec
                                             # and regenerate all consumers

With -a, a word that fails is not added and the exit is 1.  Arc validation is
necessary, not sufficient: legal screening (plan §1's ten-name sweep) and the
protocol's braille-agreement + sayability checks still apply before adoption.
Exit codes: 0 = all candidates pass (and were added, with -a),
1 = at least one candidate fails, 2 = the spec itself is broken.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import haptic_timing as ht   # the one validation engine


def arc_str(spec, word):
    return "-".join(str(spec["letters"][ch]) for ch in word)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Check (or add) protocol §5 option-B rename candidates")
    ap.add_argument("words", nargs="+", help="candidate words, lowercase a-z")
    ap.add_argument("-a", "--add", action="store_true",
                    help="add passing words to the spec's rename_examples and regenerate consumers")
    args = ap.parse_args(argv)

    problems = []
    spec = ht.load_spec(problems)
    if spec is None or problems:
        for p in problems:
            print("spec error:", p, file=sys.stderr)
        return 2

    rex = spec.get("rename_examples")
    if rex is None:
        print("spec error: no rename_examples block — cannot resolve the arc", file=sys.stderr)
        return 2
    mark = rex["same_arc_as"]
    mark_word = "".join(spec["marks"][mark])
    arc = [spec["letters"][ch] for ch in spec["marks"][mark]]
    print(f"mark: {mark} ({mark_word}) — arc {'-'.join(str(d) for d in arc)} "
          f"({ht.arc_name(arc)})")

    passing, failing = [], []
    for w in args.words:
        w = w.strip().lower()
        errs = ht.rename_word_problems(spec, w)
        if errs:
            failing.append((w, errs))
            for e in errs:
                print(f"FAIL {e}")
        else:
            passing.append(w)
            if rex and w in rex.get("words", []):
                print(f"ok   {w} ({arc_str(spec, w)}) — already in the spec")
            else:
                print(f"ok   {w} ({arc_str(spec, w)}) — spells the {mark} arc")

    if args.add:
        fresh = [w for w in passing
                 if w not in rex.setdefault("words", [])]
        if failing:
            print("nothing added — every listed word must pass before -a touches the spec")
        elif not fresh:
            print("nothing to add")
        else:
            existing = set(rex["words"])
            rex["words"] = rex["words"] + [w for w in fresh if w not in existing]
            ht.SPEC_PATH.write_text(
                json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            print(f"spec: added {', '.join(fresh)} to rename_examples.words")
            regen = []
            if not ht.write_consumers(spec, regen):
                for p in regen:
                    print("error:", p, file=sys.stderr)
                return 2
            print("consumers regenerated (feel-tool block, firmware header, spec doc)")
            print("next: commit docs/haptic-timing.json and the regenerated files together — "
                  "the pre-commit hook verifies the pair")

    if failing:
        return 1
    print("all candidates pass the arc check"
          + (" — arc validation is necessary, not sufficient: legal screening (plan §1) "
             "and braille agreement still apply" if not args.add else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
