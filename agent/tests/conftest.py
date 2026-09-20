"""agent/tests/conftest.py - path setup for the Ziv suite.

Deliberately minimal: this conftest never imports a SkillForge module
(the project moved to its own repo at the 2026-09-17 handover — see
docs/HANDOVER_SKILLFORGE.md). Only agent/ and the generated timing
module (tools/) go on sys.path.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in __import__("sys").path:
        __import__("sys").path.insert(0, _p)
