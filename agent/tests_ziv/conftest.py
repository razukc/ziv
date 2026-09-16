"""agent/tests_ziv/conftest.py - path setup for the Ziv track suite.

Deliberately minimal and SkillForge-free: this conftest never imports
server / pipeline_store / relay_compose, so the Ziv suite runs (and
fails) independently of the SkillForge track. Only the shared layer
(agent/) and the generated timing module (tools/) go on sys.path.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in __import__("sys").path:
        __import__("sys").path.insert(0, _p)
